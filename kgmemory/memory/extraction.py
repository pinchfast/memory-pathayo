from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any

from kgmemory.core.config import settings
from kgmemory.core.logger import logger
from kgmemory.llm.client import get_llm
from kgmemory.llm.parsing import parse_json_response
from kgmemory.llm.prompts import FACT_EXTRACTION_PROMPT

from .repository import build_fact_from_raw
from .schemas import Fact

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


class ExtractionError(Exception):
    pass


def chunk_message(message: str, chunk_chars: int | None = None) -> list[str]:
    limit = chunk_chars or settings.INGEST_CHUNK_CHARS
    if len(message) <= limit:
        return [message]
    chunks: list[str] = []
    current = ""
    for paragraph in message.split("\n\n"):
        pieces = [paragraph] if len(paragraph) <= limit else _split_sentences(paragraph, limit)
        for piece in pieces:
            if current and len(current) + len(piece) + 2 > limit:
                chunks.append(current)
                current = piece
            else:
                current = f"{current}\n\n{piece}" if current else piece
    if current:
        chunks.append(current)
    return chunks


def _split_sentences(text: str, limit: int) -> list[str]:
    pieces, current = [], ""
    for sentence in _SENTENCE_RE.split(text):
        while len(sentence) > limit:
            pieces.append(sentence[:limit])
            sentence = sentence[limit:]
        if current and len(current) + len(sentence) + 1 > limit:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}" if current else sentence
    if current:
        pieces.append(current)
    return pieces


async def extract_facts(
    message: str,
    *,
    speaker: str,
    speaker_role: str,
    episode_id: str,
    timestamp: datetime,
    project: str | None,
) -> tuple[list[Fact], list[dict[str, str]], int]:
    """Extract facts from all chunks. Raises ExtractionError if every chunk fails."""
    chunks = chunk_message(message)
    semaphore = asyncio.Semaphore(settings.INGEST_MAX_EXTRACT_CONCURRENCY)

    async def _extract_chunk(chunk: str) -> tuple[list[dict], list[dict]]:
        async with semaphore:
            prompt = FACT_EXTRACTION_PROMPT.format(
                speaker=speaker,
                speaker_role=speaker_role,
                timestamp=timestamp.isoformat(),
                message=chunk,
            )
            response = await get_llm().complete(prompt, kind="extraction")
            payload = parse_json_response(response)
            if not isinstance(payload, dict):
                raise ValueError("Extraction payload is not an object")
            return payload.get("facts") or [], payload.get("relations") or []

    results = await asyncio.gather(*(_extract_chunk(c) for c in chunks), return_exceptions=True)
    facts: list[Fact] = []
    relations: list[dict[str, str]] = []
    local_to_fact: dict[str, str] = {}
    failed_chunks = 0
    for index, result in enumerate(results):
        if isinstance(result, BaseException):
            failed_chunks += 1
            logger.warning(f"Extraction failed for chunk {index}: {result}")
            continue
        raw_facts, raw_relations = result
        chunk_local: dict[str, str] = {}
        for raw in raw_facts:
            if not isinstance(raw, dict):
                continue
            fact = build_fact_from_raw(
                raw,
                speaker=speaker,
                speaker_role=speaker_role,
                episode_id=episode_id,
                timestamp=timestamp,
                project=project,
            )
            if fact is None:
                continue
            local_id = str(raw.get("local_id") or "")
            if local_id:
                chunk_local[local_id] = fact.fact_id
            facts.append(fact)
        relations.extend(_resolve_relations(raw_relations, chunk_local))
        local_to_fact.update(chunk_local)

    if failed_chunks == len(chunks):
        raise ExtractionError(f"All {len(chunks)} extraction chunks failed")
    return _dedupe_by_id(facts), relations, failed_chunks


def _resolve_relations(
    raw_relations: list[Any], local_to_fact: dict[str, str]
) -> list[dict[str, str]]:
    resolved = []
    for raw in raw_relations:
        if not isinstance(raw, dict):
            continue
        source = local_to_fact.get(str(raw.get("from") or ""))
        target = local_to_fact.get(str(raw.get("to") or ""))
        relation_type = str(raw.get("type") or "").strip().lower()
        if source and target and relation_type in {"causes", "influences", "blocks", "depends_on"}:
            resolved.append({"from": source, "to": target, "type": relation_type})
    return resolved


def _dedupe_by_id(facts: list[Fact]) -> list[Fact]:
    seen: dict[str, Fact] = {}
    for fact in facts:
        seen.setdefault(fact.fact_id, fact)
    return list(seen.values())
