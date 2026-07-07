from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from kgmemory.core.config import settings
from kgmemory.core.logger import logger
from kgmemory.llm.client import LLMError, get_llm
from kgmemory.llm.parsing import parse_json_response
from kgmemory.llm.prompts import ASSOCIATIVE_RANKING_PROMPT, QUERY_INTENT_PROMPT


async def extract_intent(query: str) -> dict[str, Any]:
    try:
        response = await get_llm().complete(
            QUERY_INTENT_PROMPT.format(query=query), kind="intent", max_tokens=600
        )
        payload = parse_json_response(response)
        return payload if isinstance(payload, dict) else {}
    except (LLMError, ValueError) as exc:
        logger.warning(f"Intent extraction failed: {exc}")
        return {}


async def rank_associatively(query: str, facts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not facts:
        return {}
    lines = [
        f"- fact_id={f['fact_id']} [{f['fact_kind']}] {f['subject']} {f['predicate']} {f['value']}"
        for f in facts
    ]
    try:
        response = await get_llm().complete(
            ASSOCIATIVE_RANKING_PROMPT.format(query=query, facts="\n".join(lines)),
            kind="ranking",
        )
        payload = parse_json_response(response)
    except (LLMError, ValueError) as exc:
        logger.warning(f"Associative ranking failed: {exc}")
        return {}
    scores = {}
    for item in payload.get("scores", []) if isinstance(payload, dict) else []:
        fact_id = str(item.get("fact_id") or "")
        if fact_id:
            scores[fact_id] = {
                "relevance": max(0.0, min(1.0, float(item.get("relevance") or 0.0))),
                "connection": str(item.get("connection") or "contextual"),
                "reasoning": str(item.get("reasoning") or "")[:280],
            }
    return scores


def recency_score(valid_from: str | None) -> float:
    if not valid_from:
        return 0.5
    try:
        moment = datetime.fromisoformat(valid_from)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
    except ValueError:
        return 0.5
    age_days = max(0.0, (datetime.now(timezone.utc) - moment).total_seconds() / 86400)
    return 0.5 ** (age_days / settings.CONTEXT_RECENCY_HALF_LIFE_DAYS)
