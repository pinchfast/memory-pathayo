from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

from kgmemory.core.config import settings
from kgmemory.graph.client import get_org_store
from kgmemory.llm.embeddings import get_embedder
from kgmemory.memory.repository import FactRepository
from kgmemory.state.repository import latest_person_states, latest_project_states

from .retrievers import extract_intent, rank_associatively, recency_score


async def search_context(
    graph_name: str, query: str, *, max_facts: int | None = None, rerank: bool = True
) -> dict[str, Any]:
    started = time.perf_counter()
    budget = max_facts or settings.CONTEXT_MAX_FACTS
    store = await get_org_store(graph_name)
    repo = FactRepository(store)

    intent, query_embedding, project_states, person_states = await asyncio.gather(
        extract_intent(query),
        get_embedder().embed(query),
        latest_project_states(store),
        latest_person_states(store),
    )

    topics = [str(t).strip().lower() for t in intent.get("topics") or []][:12]
    entities = [str(e) for e in intent.get("entities") or []][:12]
    fact_kind_hints = [str(k).strip().lower() for k in intent.get("fact_kind_hints") or []][:12]
    temporal_scope = str(intent.get("temporal_scope") or "any").strip().lower()

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

    # Enrich facts with computed is_overdue flag
    now = datetime.now(timezone.utc)
    for fact in candidates.values():
        fact["is_overdue"] = _compute_is_overdue(fact, now)

    # Temporal scope filtering: if the query is about "current" status,
    # deprioritize superseded/historical facts
    if temporal_scope == "current":
        candidates = {
            fid: f for fid, f in candidates.items()
            if f.get("temporal_status") == "current"
        }

    scored = _dense_rank(list(candidates.values()), topics, fact_kind_hints)
    shortlist = scored[: max(budget * 3, 30)]

    associations = await rank_associatively(query, shortlist) if rerank else {}
    selected = _select(shortlist, associations, budget, rerank)

    return {
        "query": query,
        "intent": intent,
        "facts": selected,
        "associations": {f["fact_id"]: associations.get(f["fact_id"], {}) for f in selected},
        "project_states": project_states,
        "person_states": person_states,
        "prompt_context": _render(selected, associations, project_states, person_states),
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


def _compute_is_overdue(fact: dict[str, Any], now: datetime) -> bool:
    """Compute whether a commitment fact is overdue at query time."""
    if not fact.get("due_date"):
        return False
    if fact.get("fact_kind") != "commitment":
        return False
    if fact.get("temporal_status") != "current":
        return False
    try:
        due = datetime.fromisoformat(fact["due_date"])
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return False
    return due < now


def _dense_rank(
    facts: list[dict[str, Any]],
    topics: list[str],
    fact_kind_hints: list[str] | None = None,
) -> list[dict[str, Any]]:
    topic_set = set(topics)
    hint_set = set(fact_kind_hints or [])
    for fact in facts:
        similarity = float(fact.get("similarity") or 0.0)
        overlap = (
            len(topic_set & set(fact.get("topics") or [])) / len(topic_set)
            if topic_set
            else 0.0
        )
        # Intent-aware boost: if the query's fact_kind_hints match the fact's kind,
        # boost the dense score. This makes "is the API on track?" surface
        # status_updates and commitments over random facts.
        kind_boost = 0.15 if hint_set and fact.get("fact_kind", "").lower() in hint_set else 0.0
        # Overdue facts are inherently high-signal — boost them
        overdue_boost = 0.1 if fact.get("is_overdue") else 0.0
        fact["dense_score"] = (
            0.65 * similarity
            + 0.12 * overlap
            + 0.13 * recency_score(fact.get("valid_from"))
            + kind_boost
            + overdue_boost
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


def _render(
    facts: list[dict[str, Any]],
    associations: dict[str, dict[str, Any]],
    project_states: list[dict[str, Any]] | None = None,
    person_states: list[dict[str, Any]] | None = None,
) -> str:
    sections: list[str] = []
    if facts:
        lines = ["RELEVANT COMPANY MEMORY:"]
        for fact in facts:
            topics = ",".join(fact.get("topics") or [])
            overdue_tag = " [OVERDUE]" if fact.get("is_overdue") else ""
            line = f"- [{fact['fact_kind']}|{topics}]{overdue_tag} {fact['subject']} {fact['predicate']} {fact['value']}"
            if fact.get("speaker"):
                line += f" (from {fact['speaker']}"
                line += f", {fact['valid_from'][:10]})" if fact.get("valid_from") else ")"
            if fact.get("due_date"):
                line += f" [due: {fact['due_date'][:10]}]"
            association = associations.get(fact["fact_id"])
            if association and association.get("reasoning"):
                line += f"\n  -> {association['reasoning']}"
            lines.append(line)
        sections.append("\n".join(lines))
    else:
        sections.append("No relevant memory found.")

    if project_states:
        lines = ["CURRENT PROJECT STATES:"]
        for state in project_states:
            signals = "; ".join(state.get("risk_signals") or []) or "none"
            lines.append(
                f"- {state['project']} [{state['health']}, score {state['health_score']}]: "
                f"{state.get('summary') or 'no summary'} (risks: {signals})"
            )
        sections.append("\n".join(lines))

    if person_states:
        lines = ["CURRENT PERSON CREDIBILITY:"]
        for state in person_states:
            signals = "; ".join(state.get("risk_signals") or []) or "none"
            lines.append(
                f"- {state['person']} [{state['credibility']}, score {state['credibility_score']}]: "
                f"{state.get('summary') or 'no summary'} (risks: {signals})"
            )
        sections.append("\n".join(lines))

    return "\n\n".join(sections)
