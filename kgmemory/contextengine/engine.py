from __future__ import annotations

import asyncio
import time
from typing import Any

from kgmemory.core.config import settings
from kgmemory.graph.client import get_org_store
from kgmemory.llm.embeddings import get_embedder
from kgmemory.memory.repository import FactRepository

from .retrievers import extract_intent, rank_associatively, recency_score


async def search_context(
    graph_name: str, query: str, *, max_facts: int | None = None, rerank: bool = True
) -> dict[str, Any]:
    started = time.perf_counter()
    budget = max_facts or settings.CONTEXT_MAX_FACTS
    repo = FactRepository(await get_org_store(graph_name))

    intent, query_embedding = await asyncio.gather(
        extract_intent(query),
        get_embedder().embed(query),
    )

    topics = [str(t).strip().lower() for t in intent.get("topics") or []][:12]
    entities = [str(e) for e in intent.get("entities") or []][:12]

    vector_hits, traversal_hits, recent = await asyncio.gather(
        repo.vector_search(query_embedding, settings.CONTEXT_DENSE_TOP_K),
        repo.traverse(topics, entities, settings.CONTEXT_TRAVERSAL_MAX_HOPS),
        repo.recent_facts(limit=budget),
    )

    candidates: dict[str, dict[str, Any]] = {}
    for fact in vector_hits + traversal_hits + recent:
        existing = candidates.setdefault(fact["fact_id"], fact)
        if "similarity" in fact:
            existing["similarity"] = fact["similarity"]

    scored = _dense_rank(list(candidates.values()), topics)
    shortlist = scored[: max(budget * 3, 30)]

    associations = await rank_associatively(query, shortlist) if rerank else {}
    selected = _select(shortlist, associations, budget, rerank)

    return {
        "query": query,
        "intent": intent,
        "facts": selected,
        "associations": {f["fact_id"]: associations.get(f["fact_id"], {}) for f in selected},
        "prompt_context": _render(selected, associations),
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


def _dense_rank(facts: list[dict[str, Any]], topics: list[str]) -> list[dict[str, Any]]:
    topic_set = set(topics)
    for fact in facts:
        similarity = float(fact.get("similarity") or 0.0)
        overlap = (
            len(topic_set & set(fact.get("topics") or [])) / len(topic_set)
            if topic_set
            else 0.0
        )
        fact["dense_score"] = (
            0.7 * similarity + 0.15 * overlap + 0.15 * recency_score(fact.get("valid_from"))
        )
    return sorted(facts, key=lambda f: f["dense_score"], reverse=True)


def _select(
    facts: list[dict[str, Any]],
    associations: dict[str, dict[str, Any]],
    budget: int,
    rerank: bool,
) -> list[dict[str, Any]]:
    for fact in facts:
        llm_score = associations.get(fact["fact_id"], {}).get("relevance", 0.0)
        fact["final_score"] = (
            settings.CONTEXT_LLM_WEIGHT * llm_score
            + settings.CONTEXT_DENSE_WEIGHT * fact["dense_score"]
            if rerank and associations
            else fact["dense_score"]
        )
    ranked = sorted(facts, key=lambda f: f["final_score"], reverse=True)
    selected = [f for f in ranked if f["final_score"] >= settings.CONTEXT_MIN_RELEVANCE]
    return (selected or ranked[:5])[:budget]


def _render(facts: list[dict[str, Any]], associations: dict[str, dict[str, Any]]) -> str:
    if not facts:
        return "No relevant memory found."
    lines = ["RELEVANT COMPANY MEMORY:"]
    for fact in facts:
        topics = ",".join(fact.get("topics") or [])
        line = f"- [{fact['fact_kind']}|{topics}] {fact['subject']} {fact['predicate']} {fact['value']}"
        if fact.get("speaker"):
            line += f" (from {fact['speaker']}"
            line += f", {fact['valid_from'][:10]})" if fact.get("valid_from") else ")"
        association = associations.get(fact["fact_id"])
        if association and association.get("reasoning"):
            line += f"\n  -> {association['reasoning']}"
        lines.append(line)
    return "\n".join(lines)
