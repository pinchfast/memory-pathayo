from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from kgmemory.core.config import settings
from kgmemory.core.logger import logger
from kgmemory.core.metrics import FACTS_INGESTED
from kgmemory.graph.client import get_org_store
from kgmemory.llm.embeddings import get_embedder

from .extraction import extract_facts
from .repository import FactRepository
from .schemas import IngestRequest


async def ingest_message(graph_name: str, payload: IngestRequest) -> dict:
    message = payload.message.strip()[: settings.INGEST_MAX_MESSAGE_CHARS]
    timestamp = payload.timestamp or datetime.now(timezone.utc)
    episode_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"episode:{graph_name}:{payload.session_id}:{payload.speaker}:{timestamp.isoformat()}",
        )
    )
    store = await get_org_store(graph_name)
    repo = FactRepository(store)
    await repo.create_episode(
        episode_id, payload.channel, payload.speaker, payload.session_id, timestamp
    )

    facts, relations, failed_chunks = await extract_facts(
        message,
        speaker=payload.speaker,
        speaker_role=payload.speaker_role.value,
        episode_id=episode_id,
        timestamp=timestamp,
        project=payload.project,
    )

    if facts:
        embeddings = await get_embedder().embed_batch([f.embedding_text for f in facts])
        for fact, embedding in zip(facts, embeddings):
            fact.embedding = embedding

        overrides = await repo.find_duplicate_ids(facts)
        for fact in facts:
            if fact.fact_id in overrides:
                replacement = overrides[fact.fact_id]
                for relation in relations:
                    if relation["from"] == fact.fact_id:
                        relation["from"] = replacement
                    if relation["to"] == fact.fact_id:
                        relation["to"] = replacement
                fact.fact_id = replacement

        invalidated = await repo.supersede_conflicting(facts)
        created = await repo.upsert_facts(facts)
        await repo.link_bridges(facts)
        relations_created = await repo.link_relations(relations)
        contradictions = await repo.detect_contradictions(facts)
    else:
        invalidated = created = relations_created = 0
        contradictions = []

    FACTS_INGESTED.labels(graph_name).inc(created)
    result = {
        "episode_id": episode_id,
        "facts_extracted": len(facts),
        "facts_created": created,
        "facts_invalidated": invalidated,
        "relations_created": relations_created,
        "contradictions": contradictions,
        "failed_chunks": failed_chunks,
    }
    logger.info(f"Ingested message into {graph_name}: {result}")

    # Harness loop: fire-and-forget state inference so the PM's model of reality
    # stays in sync after every conversation. Never blocks the ingest response.
    asyncio.create_task(_safe_infer_state(graph_name))
    return result


async def _safe_infer_state(graph_name: str) -> None:
    try:
        from kgmemory.state.inference import infer_and_snapshot_state

        await infer_and_snapshot_state(graph_name)
    except Exception:
        logger.exception(f"Fire-and-forget state inference failed for {graph_name}")


async def ingest_batch(graph_name: str, messages: list[IngestRequest]) -> dict:
    """Ingest multiple messages efficiently. Embeds facts in batch across all
    messages, defers state inference until the end. Returns aggregate stats."""
    from kgmemory.memory.extraction import extract_facts

    all_facts: list = []
    all_relations: list = []
    total_failed_chunks = 0
    episode_count = 0

    store = await get_org_store(graph_name)
    repo = FactRepository(store)

    for payload in messages:
        message = payload.message.strip()[: settings.INGEST_MAX_MESSAGE_CHARS]
        timestamp = payload.timestamp or datetime.now(timezone.utc)
        episode_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"episode:{graph_name}:{payload.session_id}:{payload.speaker}:{timestamp.isoformat()}",
            )
        )
        await repo.create_episode(
            episode_id, payload.channel, payload.speaker, payload.session_id, timestamp
        )
        episode_count += 1

        facts, relations, failed_chunks = await extract_facts(
            message,
            speaker=payload.speaker,
            speaker_role=payload.speaker_role.value,
            episode_id=episode_id,
            timestamp=timestamp,
            project=payload.project,
        )
        all_facts.extend(facts)
        all_relations.extend(relations)
        total_failed_chunks += failed_chunks

    # Batch embed all facts at once
    total_created = 0
    total_invalidated = 0
    total_relations = 0
    contradictions: list = []

    if all_facts:
        embeddings = await get_embedder().embed_batch([f.embedding_text for f in all_facts])
        for fact, embedding in zip(all_facts, embeddings):
            fact.embedding = embedding

        overrides = await repo.find_duplicate_ids(all_facts)
        for fact in all_facts:
            if fact.fact_id in overrides:
                replacement = overrides[fact.fact_id]
                for relation in all_relations:
                    if relation["from"] == fact.fact_id:
                        relation["from"] = replacement
                    if relation["to"] == fact.fact_id:
                        relation["to"] = replacement
                fact.fact_id = replacement

        total_invalidated = await repo.supersede_conflicting(all_facts)
        total_created = await repo.upsert_facts(all_facts)
        await repo.link_bridges(all_facts)
        total_relations = await repo.link_relations(all_relations)
        contradictions = await repo.detect_contradictions(all_facts)

    FACTS_INGESTED.labels(graph_name).inc(total_created)

    # State inference once after the whole batch
    asyncio.create_task(_safe_infer_state(graph_name))

    result = {
        "episodes_ingested": episode_count,
        "facts_extracted": len(all_facts),
        "facts_created": total_created,
        "facts_invalidated": total_invalidated,
        "relations_created": total_relations,
        "contradictions": contradictions,
        "failed_chunks": total_failed_chunks,
    }
    logger.info(f"Batch ingested into {graph_name}: {result}")
    return result
