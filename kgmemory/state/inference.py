from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from kgmemory.core.logger import logger
from kgmemory.graph.client import GraphStore, get_org_store
from kgmemory.llm.client import LLMError, get_llm
from kgmemory.llm.parsing import parse_json_response
from kgmemory.llm.prompts import PROJECT_STATE_PROMPT, PERSON_STATE_PROMPT

from .repository import iso_now, store_person_snapshot, store_project_snapshot

SINCE_WINDOW_DAYS = 14


async def infer_and_snapshot_state(graph_name: str) -> dict[str, Any]:
    """The harness loop step: derive project + person state from recent facts,
    store durable snapshots. Called fire-and-forget after ingest."""
    started = time.perf_counter()
    store = await get_org_store(graph_name)

    project_signals = await _collect_project_signals(store)
    person_signals = await _collect_person_signals(store)

    project_states, person_states = await asyncio.gather(
        asyncio.gather(*(_infer_project_state(store, name, signals)
                          for name, signals in project_signals.items())),
        asyncio.gather(*(_infer_person_state(store, name, signals)
                          for name, signals in person_signals.items())),
    )

    for state in project_states + person_states:
        if state.get("health") or state.get("credibility"):
            await _store(store, state)

    elapsed = int((time.perf_counter() - started) * 1000)
    logger.info(
        f"State inference for {graph_name}: {len(project_states)} projects, "
        f"{len(person_states)} people, {elapsed}ms"
    )
    return {
        "projects": project_states,
        "people": person_states,
        "inferred_at": iso_now(),
        "elapsed_ms": elapsed,
    }


async def _collect_project_signals(store: GraphStore) -> dict[str, dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=SINCE_WINDOW_DAYS)).isoformat()
    rows = await store.query(
        "MATCH (f:Fact) WHERE f.temporal_status = 'current' AND f.valid_from >= $since "
        "AND f.project IS NOT NULL "
        "AND NOT (f.fact_kind = 'commitment' AND (f)-[:FULFILLED_BY]->(:Fact)) "
        "RETURN f.project, f.fact_kind, f.speaker, f.value, f.valid_from, f.due_date",
        {"since": since},
    )
    signals: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "commitments": [],
            "completed": [],
            "missed": [],
            "blockers": [],
            "engineers": set(),
            "last_activity": None,
            "facts": [],
        }
    )
    for row in rows:
        project, kind, speaker, value, valid_from, due_date = row
        bucket = signals[project]
        bucket["facts"].append({"kind": kind, "speaker": speaker, "value": value,
                                "valid_from": valid_from, "due_date": due_date})
        if kind == "commitment":
            bucket["commitments"].append({"speaker": speaker, "value": value, "due_date": due_date})
        elif kind == "status_update":
            bucket["completed"].append({"speaker": speaker, "value": value, "valid_from": valid_from})
        elif kind == "performance":
            bucket["missed"].append({"speaker": speaker, "value": value, "valid_from": valid_from})
        elif kind == "blocker":
            bucket["blockers"].append({"speaker": speaker, "value": value})
        if speaker:
            bucket["engineers"].add(speaker)
        if valid_from and (bucket["last_activity"] is None or valid_from > bucket["last_activity"]):
            bucket["last_activity"] = valid_from
    return signals


async def _collect_person_signals(store: GraphStore) -> dict[str, dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=SINCE_WINDOW_DAYS)).isoformat()
    rows = await store.query(
        "MATCH (p:Person)-[:STATED]->(f:Fact) "
        "WHERE f.temporal_status = 'current' AND f.valid_from >= $since "
        "AND NOT (f.fact_kind = 'commitment' AND (f)-[:FULFILLED_BY]->(:Fact)) "
        "RETURN p.name, f.fact_kind, f.value, f.valid_from, f.due_date",
        {"since": since},
    )
    signals: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "commitments": [],
            "completed": [],
            "missed": [],
            "last_seen": None,
            "facts": [],
        }
    )
    for row in rows:
        person, kind, value, valid_from, due_date = row
        bucket = signals[person]
        bucket["facts"].append({"kind": kind, "value": value, "valid_from": valid_from})
        if kind == "commitment":
            bucket["commitments"].append({"value": value, "due_date": due_date})
        elif kind == "status_update":
            bucket["completed"].append({"value": value, "valid_from": valid_from})
        elif kind == "performance":
            bucket["missed"].append({"value": value, "valid_from": valid_from})
        if valid_from and (bucket["last_seen"] is None or valid_from > bucket["last_seen"]):
            bucket["last_seen"] = valid_from
    return signals


async def _infer_project_state(
    store: GraphStore, project: str, signals: dict[str, Any]
) -> dict[str, Any]:
    deterministic = _deterministic_project_health(signals)
    summary = await _llm_project_summary(project, signals, deterministic)
    state = {
        "project": project,
        "health": summary.get("health", deterministic["health"]),
        "health_score": summary.get("health_score", deterministic["health_score"]),
        "open_commitments": len(signals["commitments"]),
        "completed_since_last": len(signals["completed"]),
        "missed_or_late": len(signals["missed"]),
        "open_blockers": len(signals["blockers"]),
        "active_engineers": len(signals["engineers"]),
        "last_activity": signals["last_activity"],
        "risk_signals": summary.get("risk_signals", deterministic["risk_signals"]),
        "summary": summary.get("summary", ""),
        "inferred_at": iso_now(),
    }
    return state


async def _infer_person_state(
    store: GraphStore, person: str, signals: dict[str, Any]
) -> dict[str, Any]:
    deterministic = _deterministic_person_credibility(signals)
    summary = await _llm_person_summary(person, signals, deterministic)
    days_since = _days_since(signals["last_seen"])
    state = {
        "person": person,
        "credibility": summary.get("credibility", deterministic["credibility"]),
        "credibility_score": summary.get("credibility_score", deterministic["credibility_score"]),
        "open_commitments": len(signals["commitments"]),
        "completed_since_last": len(signals["completed"]),
        "missed_or_late": len(signals["missed"]),
        "last_seen": signals["last_seen"],
        "days_since_last_seen": days_since,
        "risk_signals": summary.get("risk_signals", deterministic["risk_signals"]),
        "summary": summary.get("summary", ""),
        "inferred_at": iso_now(),
    }
    return state


def _deterministic_project_health(signals: dict[str, Any]) -> dict[str, Any]:
    commitments = len(signals["commitments"])
    completed = len(signals["completed"])
    missed = len(signals["missed"])
    blockers = len(signals["blockers"])
    risk_signals: list[str] = []
    if missed >= 2:
        risk_signals.append(f"{missed} performance concerns in last {SINCE_WINDOW_DAYS} days")
    if blockers and not completed:
        risk_signals.append(f"{blockers} open blockers, no completions")
    if commitments > 5 and completed == 0:
        risk_signals.append(f"{commitments} open commitments, none completed")
    if not signals["last_activity"]:
        risk_signals.append("no recent activity")

    score = 0.5 + 0.1 * (completed - missed) - 0.05 * blockers
    score = max(0.0, min(1.0, score))
    if blockers and not completed:
        health = "blocked"
    elif missed >= 2 or score < 0.35:
        health = "delayed"
    elif risk_signals:
        health = "at_risk"
    elif completed and not missed:
        health = "on_track"
    else:
        health = "unknown"
    return {"health": health, "health_score": round(score, 2), "risk_signals": risk_signals}


def _deterministic_person_credibility(signals: dict[str, Any]) -> dict[str, Any]:
    commitments = len(signals["commitments"])
    completed = len(signals["completed"])
    missed = len(signals["missed"])
    total = commitments + completed + missed
    risk_signals: list[str] = []
    if missed >= 2:
        risk_signals.append(f"{missed} missed/flagged in last {SINCE_WINDOW_DAYS} days")
    days = _days_since(signals["last_seen"])
    if days is not None and days >= 5:
        risk_signals.append(f"not seen in {days} days")
    if total == 0:
        score = 0.5
    else:
        score = max(0.0, min(1.0, (completed + 0.5 * commitments - 2 * missed) / total))
    if score >= 0.7:
        credibility = "high"
    elif score >= 0.4:
        credibility = "moderate"
    else:
        credibility = "low"
    return {"credibility": credibility, "credibility_score": round(score, 2), "risk_signals": risk_signals}


def _days_since(last_seen: str | None) -> int | None:
    if not last_seen:
        return None
    try:
        moment = datetime.fromisoformat(last_seen)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return max(0, (datetime.now(timezone.utc) - moment).days)


async def _llm_project_summary(
    project: str, signals: dict[str, Any], deterministic: dict[str, Any]
) -> dict[str, Any]:
    facts_text = _format_signals(signals["facts"][:30])
    prompt = PROJECT_STATE_PROMPT.format(
        project=project,
        deterministic_health=deterministic["health"],
        deterministic_score=deterministic["health_score"],
        risk_signals=", ".join(deterministic["risk_signals"]) or "none",
        facts=facts_text,
    )
    try:
        response = await get_llm().complete(prompt, kind="project_state", max_tokens=600)
        payload = parse_json_response(response)
        if isinstance(payload, dict):
            return payload
    except (LLMError, ValueError) as exc:
        logger.warning(f"Project state LLM synthesis failed for {project}: {exc}")
    return {}


async def _llm_person_summary(
    person: str, signals: dict[str, Any], deterministic: dict[str, Any]
) -> dict[str, Any]:
    facts_text = _format_signals(signals["facts"][:30])
    prompt = PERSON_STATE_PROMPT.format(
        person=person,
        deterministic_credibility=deterministic["credibility"],
        deterministic_score=deterministic["credibility_score"],
        risk_signals=", ".join(deterministic["risk_signals"]) or "none",
        facts=facts_text,
    )
    try:
        response = await get_llm().complete(prompt, kind="person_state", max_tokens=500)
        payload = parse_json_response(response)
        if isinstance(payload, dict):
            return payload
    except (LLMError, ValueError) as exc:
        logger.warning(f"Person state LLM synthesis failed for {person}: {exc}")
    return {}


def _format_signals(facts: list[dict[str, Any]]) -> str:
    if not facts:
        return "(no recent facts)"
    lines = []
    for fact in facts:
        date = (fact.get("valid_from") or "")[:10]
        lines.append(f"- [{date}] {fact.get('kind')}: {fact.get('value')}")
    return "\n".join(lines)


async def _store(store: GraphStore, state: dict[str, Any]) -> None:
    try:
        if state.get("health"):
            await store_project_snapshot(store, state)
        elif state.get("credibility"):
            await store_person_snapshot(store, state)
    except Exception:
        logger.exception(f"Failed to store state snapshot: {state.get('project') or state.get('person')}")
