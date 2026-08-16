"""Proactive check-in generation.

The PM doesn't wait to be asked — it proactively reaches out to silent or
at-risk engineers. This module generates check-in messages for specific people
or auto-detects who needs checking in based on silence + open commitments.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from kgmemory.core.logger import logger
from kgmemory.graph.client import GraphStore, get_org_store
from kgmemory.llm.client import LLMError, get_llm
from kgmemory.llm.parsing import parse_json_response
from kgmemory.llm.prompts import CHECKIN_PROMPT

SILENCE_THRESHOLD_DAYS = 4


async def check_in_person(graph_name: str, person: str) -> dict[str, Any]:
    """Generate a proactive check-in message for a specific person."""
    started = time.perf_counter()
    store = await get_org_store(graph_name)

    signals = await _collect_person_signals(store, person)
    reason = _derive_check_in_reason(signals)
    if reason is None:
        return {
            "person": person,
            "needed": False,
            "message": f"No check-in needed for {person} — they're active and on track.",
            "check_in_message": None,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }

    check_in = await _generate_check_in_message(person, reason, signals)
    check_in_msg = check_in.get("check_in_message", "")
    # Store the check-in message as a fact so the PM remembers what it asked
    # and doesn't repeat the same question next time.
    if check_in_msg:
        await _record_check_in(store, person, check_in_msg)
    elapsed = int((time.perf_counter() - started) * 1000)
    return {
        "person": person,
        "needed": True,
        "reason": reason,
        "check_in_message": check_in_msg,
        "tone": check_in.get("tone", "friendly_concerned"),
        "specific_questions": check_in.get("specific_questions", []),
        "open_commitments": signals["commitments"],
        "days_since_last_seen": signals["days_since_last_seen"],
        "elapsed_ms": elapsed,
    }


async def check_in_auto(graph_name: str) -> dict[str, Any]:
    """Auto-detect who needs checking in and generate messages for all of them."""
    started = time.perf_counter()
    store = await get_org_store(graph_name)
    people = await _find_people_needing_check_in(store)

    if not people:
        return {
            "graph_name": graph_name,
            "check_ins": [],
            "message": "No one needs checking in right now.",
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }

    check_ins = []
    for person_name, signals in people:
        reason = _derive_check_in_reason(signals)
        if reason is None:
            continue
        check_in = await _generate_check_in_message(person_name, reason, signals)
        check_in_msg = check_in.get("check_in_message", "")
        # Store the check-in message so the PM doesn't repeat it next time
        if check_in_msg:
            await _record_check_in(store, person_name, check_in_msg)
        check_ins.append({
            "person": person_name,
            "needed": True,
            "reason": reason,
            "check_in_message": check_in_msg,
            "tone": check_in.get("tone", "friendly_concerned"),
            "specific_questions": check_in.get("specific_questions", []),
            "open_commitments": signals["commitments"],
            "days_since_last_seen": signals["days_since_last_seen"],
        })

    return {
        "graph_name": graph_name,
        "check_ins": check_ins,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


async def _collect_person_signals(store: GraphStore, person: str) -> dict[str, Any]:
    """Collect signals about a person for check-in reasoning."""
    person_lower = person.strip().lower()
    rows = await store.query(
        "MATCH (p:Person)-[:STATED]->(f:Fact) "
        "WHERE f.temporal_status = 'current' AND toLower(p.name) = $person "
        "RETURN f.fact_kind, f.value, f.valid_from, f.due_date, f.project "
        "ORDER BY f.valid_from DESC LIMIT 30",
        {"person": person_lower},
    )
    commitments: list[dict] = []
    recent_facts: list[str] = []
    last_seen: str | None = None
    has_overdue = False
    now = datetime.now(timezone.utc)

    for row in rows:
        kind, value, valid_from, due_date, project = row
        if kind == "commitment":
            entry = {"value": value, "due_date": due_date, "project": project}
            commitments.append(entry)
            if due_date:
                try:
                    due = datetime.fromisoformat(due_date)
                    if due.tzinfo is None:
                        due = due.replace(tzinfo=timezone.utc)
                    if due < now:
                        has_overdue = True
                except (ValueError, TypeError):
                    pass
        recent_facts.append(f"[{kind}] {value}")
        if valid_from and (last_seen is None or valid_from > last_seen):
            last_seen = valid_from

    # Collect previous check-in messages so the PM doesn't repeat itself.
    # Check-in messages are stored as facts with kind "check_in".
    prev_checkins = await store.query(
        "MATCH (p:Person)-[:STATED]->(f:Fact) "
        "WHERE toLower(p.name) = $person AND f.fact_kind = 'check_in' "
        "RETURN f.value ORDER BY f.valid_from DESC LIMIT 3",
        {"person": person_lower},
    )
    previous_checkins = [row[0] for row in prev_checkins if row[0]]

    days_since = _days_since(last_seen)
    return {
        "commitments": commitments,
        "recent_facts": recent_facts[:10],
        "last_seen": last_seen,
        "days_since_last_seen": days_since,
        "has_overdue": has_overdue,
        "previous_checkins": previous_checkins,
    }


async def _find_people_needing_check_in(store: GraphStore) -> list[tuple[str, dict[str, Any]]]:
    """Find all people who need a check-in based on silence + open commitments.

    Two groups:
    1. People with open commitments who've been silent (priority)
    2. People who've been silent for the threshold period even without commitments
       (casual check-in to maintain engagement)
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=SILENCE_THRESHOLD_DAYS)).isoformat()

    # Group 1: people with open commitments who haven't been seen recently
    rows = await store.query(
        "MATCH (p:Person)-[:STATED]->(c:Fact) "
        "WHERE c.temporal_status = 'current' AND c.fact_kind = 'commitment' "
        "WITH p, c "
        "OPTIONAL MATCH (p)-[:STATED]->(recent:Fact) "
        "WHERE recent.temporal_status = 'current' AND recent.valid_from >= $cutoff "
        "WITH p, collect(recent) AS recents "
        "WHERE size(recents) = 0 "
        "RETURN DISTINCT p.name",
        {"cutoff": cutoff},
    )

    # Group 2: people who've been silent for the threshold even without commitments
    silent_rows = await store.query(
        "MATCH (p:Person)-[:STATED]->(f:Fact) "
        "WHERE f.temporal_status = 'current' "
        "WITH p, max(f.valid_from) AS last_seen "
        "WHERE last_seen < $cutoff "
        "RETURN p.name, last_seen",
        {"cutoff": cutoff},
    )

    seen_names: set[str] = set()
    results: list[tuple[str, dict[str, Any]]] = []
    for row in rows:
        person_name = row[0]
        seen_names.add(person_name.lower())
        signals = await _collect_person_signals(store, person_name)
        results.append((person_name, signals))
    for row in silent_rows:
        person_name = row[0]
        if person_name.lower() in seen_names:
            continue
        signals = await _collect_person_signals(store, person_name)
        results.append((person_name, signals))
    return results


def _derive_check_in_reason(signals: dict[str, Any]) -> str | None:
    """Determine if a check-in is needed and why."""
    days = signals.get("days_since_last_seen")
    has_commitments = bool(signals.get("commitments"))
    has_overdue = signals.get("has_overdue", False)

    if has_overdue:
        return "has overdue commitments"
    if days is not None and days >= SILENCE_THRESHOLD_DAYS:
        if has_commitments:
            return f"has been silent for {days} days while having open commitments"
        return f"has been silent for {days} days — checking in to see how they're doing"
    if has_commitments and days is not None and days >= 2:
        return "has open commitments and hasn't provided a recent update"
    return None


async def _generate_check_in_message(
    person: str, reason: str, signals: dict[str, Any]
) -> dict[str, Any]:
    commitments_text = "; ".join(
        f"{c['value']} (due: {c['due_date'] or 'no date'})"
        for c in signals["commitments"][:5]
    ) or "(none)"
    recent_text = "\n".join(f"- {f}" for f in signals["recent_facts"][:5]) or "(no recent facts)"
    last_seen = signals.get("last_seen") or "never"
    previous_checkins = signals.get("previous_checkins", [])
    prev_text = "\n".join(f"- {m}" for m in previous_checkins) or "(none)"

    prompt = CHECKIN_PROMPT.format(
        person=person,
        reason=reason,
        commitments=commitments_text,
        last_seen=last_seen,
        recent_facts=recent_text,
        previous_checkins=prev_text,
    )
    try:
        response = await get_llm().complete(prompt, kind="checkin", max_tokens=600)
        payload = parse_json_response(response)
        if isinstance(payload, dict):
            return payload
    except (LLMError, ValueError) as exc:
        logger.warning(f"Check-in generation failed for {person}: {exc}")
    return {
        "check_in_message": (
            f"Hey {person}, I wanted to check in on your open commitments "
            f"({commitments_text}). Can you give me a concrete update by end of day?"
        ),
        "tone": "friendly_concerned",
        "specific_questions": ["What's your current progress?", "Any blockers?"],
    }


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


async def _record_check_in(store: GraphStore, person: str, message: str) -> None:
    """Record a check-in message as a fact so the PM remembers what it asked.

    This prevents the PM from repeating the same question in future check-ins.
    The fact is stored with fact_kind='check_in' and expires after 14 days
    so old check-ins don't clutter the graph forever.
    """
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(days=14)).isoformat()
    person_lower = person.strip().lower()
    # Truncate the message so it doesn't bloat the graph
    short_msg = message[:200]
    try:
        await store.query(
            "CREATE (p:Person {name: $person}), (f:Fact {"
            "  fact_kind: 'check_in', "
            "  value: $msg, "
            "  subject: $person, "
            "  predicate: 'was asked', "
            "  temporal_status: 'current', "
            "  valid_from: $now, "
            "  expires_at: $expires"
            "}) "
            "WITH p, f "
            "MERGE (p)-[:STATED]->(f)",
            {
                "person": person_lower,
                "msg": short_msg,
                "now": now.isoformat(),
                "expires": expires,
            },
        )
    except Exception as exc:
        logger.warning(f"Failed to record check-in for {person}: {exc}")
