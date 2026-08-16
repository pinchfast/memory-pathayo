from __future__ import annotations

import time
from typing import Any

from kgmemory.actions.repository import store_actions
from kgmemory.core.logger import logger
from kgmemory.graph.client import get_org_store
from kgmemory.llm.client import LLMError, get_llm
from kgmemory.llm.parsing import parse_json_response
from kgmemory.llm.prompts import PM_DECISION_PROMPT

from ..contextengine.engine import search_context
from .history import store_decision
from .schemas import DecisionRequest


def _compute_confidence(context: dict[str, Any]) -> float:
    """Compute decision confidence from context quality.

    Factors:
    - Fact count: more supporting facts = higher confidence (capped)
    - Fact recency: fresher facts = higher confidence
    - State availability: having project + person states = higher confidence
    - Source diversity: facts from multiple speakers = higher confidence
    """
    facts = context.get("facts") or []
    project_states = context.get("project_states") or []
    person_states = context.get("person_states") or []

    # Fact count score: 0 facts = 0.2, 5+ facts = 1.0 (logarithmic)
    fact_count_score = min(1.0, 0.2 + 0.3 * (len(facts) / 5)) if facts else 0.2

    # Recency score: average recency of facts
    if facts:
        from kgmemory.contextengine.retrievers import recency_score

        avg_recency = sum(recency_score(f.get("valid_from")) for f in facts) / len(facts)
    else:
        avg_recency = 0.3

    # State availability: having both project and person states boosts confidence
    state_score = 0.0
    if project_states:
        state_score += 0.15
    if person_states:
        state_score += 0.15

    # Source diversity: facts from multiple distinct speakers
    speakers = {f.get("speaker") for f in facts if f.get("speaker")}
    diversity_score = min(0.15, 0.05 * len(speakers))

    confidence = (
        0.35 * fact_count_score
        + 0.25 * avg_recency
        + state_score
        + diversity_score
    )
    return round(max(0.0, min(1.0, confidence)), 2)


async def decide(graph_name: str, request: DecisionRequest) -> dict[str, Any]:
    started = time.perf_counter()

    context = await search_context(
        graph_name, request.query, max_facts=request.max_facts, rerank=request.rerank
    )

    project_states_text = _format_project_states(context.get("project_states") or [])
    person_states_text = _format_person_states(context.get("person_states") or [])
    memory_context = context["prompt_context"]

    # Also fetch ALL people so the PM knows the full team, even those
    # without facts or states yet (e.g. not onboarded)
    from kgmemory.people.service import list_people
    store = await get_org_store(graph_name)
    all_people = await list_people(store)
    team_summary = _format_team_summary(all_people)

    prompt = PM_DECISION_PROMPT.format(
        audience=request.audience,
        query=request.query,
        project_states=project_states_text,
        person_states=person_states_text,
        memory_context=memory_context[:2000],
        team_summary=team_summary,
    )

    try:
        response = await get_llm().complete(prompt, kind="decision", max_tokens=4000)
        payload = parse_json_response(response)
        if not isinstance(payload, dict):
            raise LLMError("Decision payload is not an object")
    except Exception as exc:
        logger.exception(f"Decision synthesis failed: {exc}")
        # Build a clean fallback from team summary + person states
        # instead of dumping raw memory context
        fallback_parts = []
        if team_summary and team_summary != "(no team members yet)":
            fallback_parts.append(f"Here's what I know about the team:\n{team_summary}")
        if person_states_text and person_states_text != "(no person states inferred yet)":
            fallback_parts.append(f"\nTeam status:\n{person_states_text}")
        if not fallback_parts:
            fallback_parts.append("I'm still learning about your team. Try asking me again in a moment.")
        payload = {
            "response_text": "\n".join(fallback_parts),
            "reasoning": f"LLM synthesis failed: {exc}",
            "suggested_actions": [{"action": "none", "target": "", "message": "", "urgency": "low"}],
            "risk_level": "medium",
        }

    suggested_actions = payload.get("suggested_actions") or []

    # Persist non-trivial actions to the action queue so the Django backend
    # can fetch and execute them (Slack pings, escalations, etc.).
    real_actions = [a for a in suggested_actions if a.get("action") and a["action"] != "none"]
    if real_actions:
        try:
            store = await get_org_store(graph_name)
            await store_actions(store, real_actions)
        except Exception:
            logger.exception(f"Failed to persist actions to queue for {graph_name}")

    elapsed = int((time.perf_counter() - started) * 1000)
    confidence = _compute_confidence(context)

    result = {
        "query": request.query,
        "audience": request.audience,
        "response_text": payload.get("response_text", ""),
        "reasoning": payload.get("reasoning", ""),
        "suggested_actions": suggested_actions,
        "risk_level": payload.get("risk_level", "medium"),
        "confidence": confidence,
        "context_facts": context["facts"],
        "project_states": context.get("project_states") or [],
        "person_states": context.get("person_states") or [],
        "elapsed_ms": elapsed,
    }

    # Persist the decision for audit trail and learning
    try:
        store = await get_org_store(graph_name)
        decision_id = await store_decision(store, result)
        result["decision_id"] = decision_id
    except Exception:
        logger.exception(f"Failed to store decision history for {graph_name}")

    return result


def _format_project_states(states: list[dict[str, Any]]) -> str:
    if not states:
        return "(no project states inferred yet)"
    lines = []
    for state in states:
        signals = "; ".join(state.get("risk_signals") or []) or "none"
        lines.append(
            f"- {state['project']} [{state['health']}, score {state['health_score']}]: "
            f"{state.get('summary') or 'no summary'} (risks: {signals})"
        )
    return "\n".join(lines)


def _format_person_states(states: list[dict[str, Any]]) -> str:
    if not states:
        return "(no person states inferred yet)"
    lines = []
    for state in states:
        signals = "; ".join(state.get("risk_signals") or []) or "none"
        lines.append(
            f"- {state['person']} [{state['credibility']}, score {state['credibility_score']}]: "
            f"{state.get('summary') or 'no summary'} (risks: {signals})"
        )
    return "\n".join(lines)


def _format_team_summary(people: list[dict[str, Any]]) -> str:
    if not people:
        return "(no team members yet)"
    lines = []
    for p in people:
        name = p.get("name", "unknown")
        role = p.get("role", "unknown")
        skills = p.get("skills") or []
        avail = p.get("availability_hours_per_week")
        reliability = p.get("reliability_score", 0)
        completed = p.get("completed_count", 0)
        missed = p.get("missed_count", 0)
        avail_str = f", {avail} hrs/wk" if avail else ""
        skills_str = ", ".join(skills[:10]) if skills else "no skills listed"
        lines.append(
            f"- {name} ({role}): skills=[{skills_str}]{avail_str}, "
            f"{completed} done, {missed} missed, {int(reliability * 100)}% reliable"
        )
    return "\n".join(lines)
