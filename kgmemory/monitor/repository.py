"""Alert node storage and retrieval in the graph."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from kgmemory.graph.client import GraphStore


def alert_signature(risk: dict[str, Any]) -> str:
    """Deterministic ID so the same risk doesn't create duplicate alerts."""
    raw = f"{risk['alert_type']}:{risk.get('subject', '')}:{risk.get('project', '')}:{risk.get('person', '')}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


async def store_alert(store: GraphStore, risk: dict[str, Any]) -> dict[str, Any] | None:
    """Store an Alert node, deduped by signature. Only creates a new alert if
    no open alert with the same signature exists."""
    alert_id = alert_signature(risk)
    now = datetime.now(timezone.utc).isoformat()

    # Check if an open alert with this signature already exists
    existing = await store.query(
        "MATCH (a:Alert {alert_id: $alert_id, status: 'open'}) RETURN a.alert_id",
        {"alert_id": alert_id},
    )
    if existing:
        return None  # Already alerted and not yet acknowledged

    await store.query(
        "MERGE (a:Alert {alert_id: $alert_id}) "
        "SET a.alert_type = $alert_type, a.subject = $subject, a.project = $project, "
        "a.person = $person, a.severity = $severity, a.message = $message, "
        "a.evidence_fact_id = $evidence_fact_id, a.status = 'open', "
        "a.created_at = $created_at, a.acknowledged_at = NULL "
        "WITH a "
        "OPTIONAL MATCH (p:Project {name: a.project}) "
        "FOREACH (_ IN CASE WHEN p IS NOT NULL THEN [1] ELSE [] END | "
        "  MERGE (a)-[:ABOUT_PROJECT]->(p)) "
        "OPTIONAL MATCH (pe:Person {name: a.person}) "
        "FOREACH (_ IN CASE WHEN pe IS NOT NULL THEN [1] ELSE [] END | "
        "  MERGE (a)-[:ABOUT_PERSON]->(pe))",
        {
            "alert_id": alert_id,
            "alert_type": risk["alert_type"],
            "subject": risk.get("subject", ""),
            "project": risk.get("project"),
            "person": risk.get("person"),
            "severity": risk.get("severity", "medium"),
            "message": risk.get("message", ""),
            "evidence_fact_id": risk.get("evidence_fact_id"),
            "created_at": now,
        },
    )
    return {
        "alert_id": alert_id,
        "alert_type": risk["alert_type"],
        "subject": risk.get("subject", ""),
        "project": risk.get("project"),
        "person": risk.get("person"),
        "severity": risk.get("severity", "medium"),
        "message": risk.get("message", ""),
        "status": "open",
        "created_at": now,
    }


async def list_alerts(
    store: GraphStore, *, status: str = "open", limit: int = 50
) -> list[dict[str, Any]]:
    rows = await store.query(
        "MATCH (a:Alert) "
        + ("WHERE a.status = $status " if status != "all" else "")
        + "RETURN a.alert_id, a.alert_type, a.subject, a.project, a.person, "
        "a.severity, a.message, a.evidence_fact_id, a.status, a.created_at, a.acknowledged_at "
        "ORDER BY a.created_at DESC LIMIT $limit",
        {"status": status, "limit": limit},
    )
    return [
        {
            "alert_id": r[0],
            "alert_type": r[1],
            "subject": r[2],
            "project": r[3],
            "person": r[4],
            "severity": r[5],
            "message": r[6],
            "evidence_fact_id": r[7],
            "status": r[8],
            "created_at": r[9],
            "acknowledged_at": r[10],
        }
        for r in rows
    ]


async def ack_alert(store: GraphStore, alert_id: str) -> dict[str, Any] | None:
    now = datetime.now(timezone.utc).isoformat()
    result = await store.query(
        "MATCH (a:Alert {alert_id: $alert_id}) "
        "WHERE a.status = 'open' "
        "SET a.status = 'acknowledged', a.acknowledged_at = $now "
        "RETURN a.alert_id, a.status, a.acknowledged_at",
        {"alert_id": alert_id, "now": now},
    )
    if not result:
        return None
    return {
        "alert_id": result[0][0],
        "status": result[0][1],
        "acknowledged_at": result[0][2],
    }
