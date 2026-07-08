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
from .schemas import DecisionRequest


async def decide(graph_name: str, request: DecisionRequest) -> dict[str, Any]:
    started = time.perf_counter()

    context = await search_context(
        graph_name, request.query, max_facts=request.max_facts, rerank=request.rerank
    )

    project_states_text = _format_project_states(context.get("project_states") or [])
    person_states_text = _format_person_states(context.get("person_states") or [])
    memory_context = context["prompt_context"]

    prompt = PM_DECISION_PROMPT.format(
        audience=request.audience,
        query=request.query,
        project_states=project_states_text,
        person_states=person_states_text,
        memory_context=memory_context,
    )

    try:
        response = await get_llm().complete(prompt, kind="decision", max_tokens=2000)
        payload = parse_json_response(response)
        if not isinstance(payload, dict):
            raise LLMError("Decision payload is not an object")
    except Exception as exc:
        logger.exception(f"Decision synthesis failed: {exc}")
        payload = {
            "response_text": "I couldn't fully analyze this just now. Here's what I know:\n" + memory_context,
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
    return {
        "query": request.query,
        "audience": request.audience,
        "response_text": payload.get("response_text", ""),
        "reasoning": payload.get("reasoning", ""),
        "suggested_actions": suggested_actions,
        "risk_level": payload.get("risk_level", "medium"),
        "context_facts": context["facts"],
        "project_states": context.get("project_states") or [],
        "person_states": context.get("person_states") or [],
        "elapsed_ms": elapsed,
    }


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
