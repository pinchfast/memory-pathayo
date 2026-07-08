from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from kgmemory.graph.client import GraphStore


async def store_project_snapshot(store: GraphStore, snapshot: dict[str, Any]) -> None:
    await store.query(
        "MERGE (p:Project {name: $project}) "
        "MERGE (s:StateSnapshot {snapshot_id: $snapshot_id}) "
        "SET s.kind = 'project', s.project = $project, s.health = $health, "
        "s.health_score = $health_score, s.open_commitments = $open_commitments, "
        "s.completed_since_last = $completed_since_last, s.missed_or_late = $missed_or_late, "
        "s.open_blockers = $open_blockers, s.active_engineers = $active_engineers, "
        "s.last_activity = $last_activity, s.risk_signals = $risk_signals, "
        "s.summary = $summary, s.inferred_at = $inferred_at "
        "MERGE (s)-[:DESCRIBES]->(p)",
        {
            "snapshot_id": f"proj:{snapshot['project']}:{snapshot['inferred_at']}",
            "project": snapshot["project"],
            "health": snapshot["health"],
            "health_score": snapshot["health_score"],
            "open_commitments": snapshot["open_commitments"],
            "completed_since_last": snapshot["completed_since_last"],
            "missed_or_late": snapshot["missed_or_late"],
            "open_blockers": snapshot["open_blockers"],
            "active_engineers": snapshot["active_engineers"],
            "last_activity": snapshot.get("last_activity"),
            "risk_signals": snapshot.get("risk_signals") or [],
            "summary": snapshot.get("summary") or "",
            "inferred_at": snapshot["inferred_at"],
        },
    )


async def store_person_snapshot(store: GraphStore, snapshot: dict[str, Any]) -> None:
    await store.query(
        "MERGE (p:Person {name: $person}) "
        "MERGE (s:StateSnapshot {snapshot_id: $snapshot_id}) "
        "SET s.kind = 'person', s.person = $person, s.credibility = $credibility, "
        "s.credibility_score = $credibility_score, s.open_commitments = $open_commitments, "
        "s.completed_since_last = $completed_since_last, s.missed_or_late = $missed_or_late, "
        "s.last_seen = $last_seen, s.days_since_last_seen = $days_since_last_seen, "
        "s.risk_signals = $risk_signals, s.summary = $summary, s.inferred_at = $inferred_at "
        "MERGE (s)-[:DESCRIBES]->(p)",
        {
            "snapshot_id": f"person:{snapshot['person']}:{snapshot['inferred_at']}",
            "person": snapshot["person"],
            "credibility": snapshot["credibility"],
            "credibility_score": snapshot["credibility_score"],
            "open_commitments": snapshot["open_commitments"],
            "completed_since_last": snapshot["completed_since_last"],
            "missed_or_late": snapshot["missed_or_late"],
            "last_seen": snapshot.get("last_seen"),
            "days_since_last_seen": snapshot.get("days_since_last_seen"),
            "risk_signals": snapshot.get("risk_signals") or [],
            "summary": snapshot.get("summary") or "",
            "inferred_at": snapshot["inferred_at"],
        },
    )


async def latest_project_states(store: GraphStore) -> list[dict[str, Any]]:
    rows = await store.query(
        "MATCH (s:StateSnapshot {kind: 'project'}) "
        "WITH s.project AS project, max(s.inferred_at) AS latest "
        "MATCH (s:StateSnapshot {kind: 'project', project: project, inferred_at: latest}) "
        "RETURN s.project, s.health, s.health_score, s.open_commitments, "
        "s.completed_since_last, s.missed_or_late, s.open_blockers, "
        "s.active_engineers, s.last_activity, s.risk_signals, s.summary, s.inferred_at"
    )
    return [_row_to_project_state(r) for r in rows]


async def latest_person_states(store: GraphStore) -> list[dict[str, Any]]:
    rows = await store.query(
        "MATCH (s:StateSnapshot {kind: 'person'}) "
        "WITH s.person AS person, max(s.inferred_at) AS latest "
        "MATCH (s:StateSnapshot {kind: 'person', person: person, inferred_at: latest}) "
        "RETURN s.person, s.credibility, s.credibility_score, s.open_commitments, "
        "s.completed_since_last, s.missed_or_late, s.last_seen, "
        "s.days_since_last_seen, s.risk_signals, s.summary, s.inferred_at"
    )
    return [_row_to_person_state(r) for r in rows]


def _row_to_project_state(row: list[Any]) -> dict[str, Any]:
    return {
        "project": row[0],
        "health": row[1] or "unknown",
        "health_score": float(row[2] or 0.5),
        "open_commitments": int(row[3] or 0),
        "completed_since_last": int(row[4] or 0),
        "missed_or_late": int(row[5] or 0),
        "open_blockers": int(row[6] or 0),
        "active_engineers": int(row[7] or 0),
        "last_activity": row[8],
        "risk_signals": row[9] or [],
        "summary": row[10] or "",
        "inferred_at": row[11],
    }


def _row_to_person_state(row: list[Any]) -> dict[str, Any]:
    return {
        "person": row[0],
        "credibility": row[1] or "unknown",
        "credibility_score": float(row[2] or 0.5),
        "open_commitments": int(row[3] or 0),
        "completed_since_last": int(row[4] or 0),
        "missed_or_late": int(row[5] or 0),
        "last_seen": row[6],
        "days_since_last_seen": row[7],
        "risk_signals": row[8] or [],
        "summary": row[9] or "",
        "inferred_at": row[10],
    }


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()
