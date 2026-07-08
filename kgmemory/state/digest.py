"""Founder digest — a ruthlessly filtered, honest summary for busy founders.

Only includes what the founder NEEDS to know. No padding, no jargon, no hedging.
"""
from __future__ import annotations

import time
from typing import Any

from kgmemory.core.logger import logger
from kgmemory.graph.client import get_org_store
from kgmemory.llm.client import LLMError, get_llm
from kgmemory.llm.parsing import parse_json_response
from kgmemory.llm.prompts import FOUNDER_DIGEST_PROMPT

from .repository import latest_person_states, latest_project_states


async def generate_founder_digest(
    graph_name: str, audience: str = "founder_non_technical"
) -> dict[str, Any]:
    """Generate a concise, honest digest for a founder.
    Filters everything to only what they need to know.
    """
    started = time.perf_counter()
    store = await get_org_store(graph_name)

    # Get current project states
    project_states = await latest_project_states(store)
    person_states = await latest_person_states(store)

    # Get recent alerts (unacknowledged)
    from kgmemory.monitor.repository import list_alerts
    alerts = await list_alerts(store, status="open")
    risks = [
        f"- [{a.get('severity', 'unknown')}] {a.get('alert_type')}: {a.get('message')}"
        for a in alerts[:5]
    ] or ["No active risks"]

    # Get recent completions (fulfilled commitments)
    completion_rows = await store.query(
        "MATCH (c:Fact)-[:FULFILLED_BY]->(s:Fact) "
        "WHERE c.fact_kind = 'commitment' "
        "RETURN c.subject, c.value, s.valid_from, c.project "
        "ORDER BY s.valid_from DESC LIMIT 5"
    )
    completions = [
        f"- {r[0]} completed: {r[1]}" + (f" ({r[3]})" if r[3] else "")
        for r in completion_rows
    ] or ["No recent completions"]

    # Get recent decisions
    from .history import list_decisions
    decisions = await list_decisions(store, limit=3)
    decision_lines = [
        f"- [{d.get('risk_level', 'unknown')}] {d.get('query', 'unknown')}"
        for d in decisions
    ] or ["No recent decisions"]

    # Format project states
    project_text = "\n".join(
        f"- {s.get('project')}: {s.get('health')}, score {s.get('health_score')} — {s.get('summary', '')}"
        for s in project_states[:5]
    ) or "No project states available"

    # Format person states
    person_text = "\n".join(
        f"- {s.get('person')}: {s.get('credibility')}, score {s.get('credibility_score')} — {s.get('summary', '')}"
        for s in person_states[:5]
    ) or "No person states available"

    prompt = FOUNDER_DIGEST_PROMPT.format(
        audience=audience,
        project_states=project_text,
        person_states=person_text,
        risks="\n".join(risks),
        completions="\n".join(completions),
        decisions="\n".join(decision_lines),
    )

    try:
        response = await get_llm().complete(prompt, kind="digest", max_tokens=800)
        payload = parse_json_response(response)
        if not isinstance(payload, dict):
            raise LLMError("Digest payload is not an object")
    except Exception as exc:
        logger.exception(f"Founder digest LLM failed: {exc}")
        # Fallback: simple deterministic digest
        red_projects = [s for s in project_states if s.get("health") in ("delayed", "blocked")]
        if red_projects:
            headline = f"{len(red_projects)} project(s) need your attention."
            urgency = "red"
        elif project_states:
            headline = "Projects are on track."
            urgency = "green"
        else:
            headline = "Not enough data to assess."
            urgency = "yellow"
        payload = {
            "headline": headline,
            "needs_attention": risks[:3],
            "going_well": completions[:2],
            "recommended_action": "Check in on at-risk projects" if red_projects else "Nothing needed right now",
            "urgency_level": urgency,
        }

    elapsed = int((time.perf_counter() - started) * 1000)
    payload["elapsed_ms"] = elapsed
    return payload
