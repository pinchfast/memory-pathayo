"""Autonomous monitor loop.

Scans every org's graph for time-based risks that don't surface from ingest alone:
- Overdue commitments (due_date in the past, no matching completion)
- Engineer silence (no facts from a person in N days while they have open commitments)
- Single-point-of-failure (one engineer on a project with open commitments)
- Unresolved blockers (blocker facts older than N days with no completion since)

Generates Alert nodes in the graph and deduplicates so the same risk isn't alerted
twice unless it's re-confirmed after ack.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from kgmemory.core.logger import logger
from kgmemory.graph.client import GraphStore, get_org_store
from kgmemory.orgs.models import Organization

from .repository import (
    ack_alert,
    list_alerts,
    store_alert,
)
from .webhooks import dispatch_alert_webhook_safe

SILENCE_THRESHOLD_DAYS = 4
OVERDUE_GRACE_HOURS = 2
BLOCKER_STALE_DAYS = 3


async def run_monitor_loop(graph_name: str, org: Organization | None = None) -> dict[str, Any]:
    """Scan one org's graph for time-based risks and emit Alert nodes.

    If an Organization model is passed, alerts are also dispatched via webhook.
    Returns a summary of alerts generated.
    """
    started = datetime.now(timezone.utc)
    store = await get_org_store(graph_name)

    overdue, silent, spof, stale_blockers = await asyncio.gather(
        _find_overdue_commitments(store),
        _find_silent_engineers(store),
        _find_single_points_of_failure(store),
        _find_stale_blockers(store),
    )

    generated: list[dict[str, Any]] = []
    for risk in overdue + silent + spof + stale_blockers:
        alert = await store_alert(store, risk)
        if alert:
            generated.append(alert)
            if org:
                asyncio.create_task(dispatch_alert_webhook_safe(org, alert))

    elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    logger.info(
        f"Monitor loop for {graph_name}: {len(generated)} alerts "
        f"({len(overdue)} overdue, {len(silent)} silent, {len(spof)} spof, "
        f"{len(stale_blockers)} stale blockers), {elapsed_ms}ms"
    )
    return {
        "graph_name": graph_name,
        "alerts_generated": len(generated),
        "alerts": generated,
        "checked_at": started.isoformat(),
        "elapsed_ms": elapsed_ms,
    }


async def _find_overdue_commitments(store: GraphStore) -> list[dict[str, Any]]:
    """Commitments with due_date in the past that have no matching completion."""
    now = datetime.now(timezone.utc)
    grace = (now - timedelta(hours=OVERDUE_GRACE_HOURS)).isoformat()
    rows = await store.query(
        "MATCH (f:Fact) "
        "WHERE f.temporal_status = 'current' AND f.fact_kind = 'commitment' "
        "AND f.due_date IS NOT NULL AND f.due_date < $grace "
        "OPTIONAL MATCH (c:Fact) "
        "WHERE c.temporal_status = 'current' AND c.fact_kind = 'status_update' "
        "AND c.subject = f.subject AND c.value CONTAINS f.value "
        "WITH f, c "
        "WHERE c IS NULL "
        "RETURN f.fact_id, f.subject, f.value, f.due_date, f.project, f.speaker",
        {"grace": grace},
    )
    risks: list[dict[str, Any]] = []
    for row in rows:
        fact_id, subject, value, due_date, project, speaker = row
        risks.append({
            "alert_type": "overdue_commitment",
            "subject": subject,
            "project": project,
            "person": speaker,
            "severity": "high",
            "message": f"{speaker or subject} committed to '{value}' due {due_date} — overdue.",
            "evidence_fact_id": fact_id,
            "due_date": due_date,
        })
    return risks


async def _find_silent_engineers(store: GraphStore) -> list[dict[str, Any]]:
    """People with open commitments who haven't stated any facts in N days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=SILENCE_THRESHOLD_DAYS)).isoformat()
    rows = await store.query(
        "MATCH (p:Person)-[:STATED]->(c:Fact) "
        "WHERE c.temporal_status = 'current' AND c.fact_kind = 'commitment' "
        "AND NOT EXISTS { "
        "  MATCH (p)-[:STATED]->(recent:Fact) "
        "  WHERE recent.temporal_status = 'current' AND recent.valid_from >= $cutoff "
        "} "
        "WITH p, collect(c) AS commitments "
        "OPTIONAL MATCH (p)-[:STATED]->(last:Fact) "
        "WHERE last.temporal_status = 'current' "
        "RETURN p.name, max(last.valid_from), count(commitments)",
        {"cutoff": cutoff},
    )
    risks: list[dict[str, Any]] = []
    for row in rows:
        person, last_seen, commitment_count = row
        risks.append({
            "alert_type": "engineer_silence",
            "subject": person,
            "person": person,
            "project": None,
            "severity": "medium",
            "message": (
                f"{person} has {commitment_count} open commitment(s) but hasn't been "
                f"heard from in {SILENCE_THRESHOLD_DAYS}+ days (last seen {last_seen})."
            ),
            "evidence_fact_id": None,
            "last_seen": last_seen,
        })
    return risks


async def _find_single_points_of_failure(store: GraphStore) -> list[dict[str, Any]]:
    """Projects with open commitments staffed by exactly one engineer."""
    rows = await store.query(
        "MATCH (f:Fact) "
        "WHERE f.temporal_status = 'current' AND f.fact_kind = 'commitment' AND f.project IS NOT NULL "
        "WITH f.project AS project, collect(DISTINCT f.speaker) AS engineers, count(f) AS commitment_count "
        "WHERE size(engineers) = 1 AND commitment_count >= 1 "
        "RETURN project, engineers[0], commitment_count",
    )
    risks: list[dict[str, Any]] = []
    for row in rows:
        project, engineer, count = row
        risks.append({
            "alert_type": "single_point_of_failure",
            "subject": project,
            "project": project,
            "person": engineer,
            "severity": "medium",
            "message": (
                f"Project '{project}' has {count} open commitment(s) "
                f"assigned to a single engineer ({engineer}). Bus factor = 1."
            ),
            "evidence_fact_id": None,
        })
    return risks


async def _find_stale_blockers(store: GraphStore) -> list[dict[str, Any]]:
    """Blocker facts older than N days with no completion since."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=BLOCKER_STALE_DAYS)).isoformat()
    rows = await store.query(
        "MATCH (f:Fact) "
        "WHERE f.temporal_status = 'current' AND f.fact_kind = 'blocker' "
        "AND f.valid_from < $cutoff "
        "AND NOT EXISTS { "
        "  MATCH (c:Fact) "
            "WHERE c.temporal_status = 'current' AND c.fact_kind = 'status_update' "
        "  AND c.subject = f.subject AND c.valid_from > f.valid_from "
        "} "
        "RETURN f.fact_id, f.subject, f.value, f.project, f.speaker, f.valid_from",
        {"cutoff": cutoff},
    )
    risks: list[dict[str, Any]] = []
    for row in rows:
        fact_id, subject, value, project, speaker, valid_from = row
        risks.append({
            "alert_type": "stale_blocker",
            "subject": subject,
            "project": project,
            "person": speaker,
            "severity": "high",
            "message": (
                f"Blocker '{value}' reported by {speaker or subject} on {valid_from} "
                f"is unresolved after {BLOCKER_STALE_DAYS}+ days."
            ),
            "evidence_fact_id": fact_id,
        })
    return risks


async def get_alerts(
    graph_name: str, *, status: str = "open", limit: int = 50
) -> list[dict[str, Any]]:
    store = await get_org_store(graph_name)
    return await list_alerts(store, status=status, limit=limit)


async def acknowledge_alert(graph_name: str, alert_id: str) -> dict[str, Any] | None:
    store = await get_org_store(graph_name)
    return await ack_alert(store, alert_id)


ESCALATION_THRESHOLD_HOURS = 24
_SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


async def escalate_stale_alerts(graph_name: str, org: Organization | None = None) -> dict[str, Any]:
    """Escalate alerts that have been open and unacknowledged past the threshold.

    Increases severity by one level and creates an action so the backend
    is reminded to handle it. Also re-dispatches webhook.
    """
    store = await get_org_store(graph_name)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=ESCALATION_THRESHOLD_HOURS)).isoformat()

    rows = await store.query(
        "MATCH (a:Alert {status: 'open'}) "
        "WHERE a.created_at < $cutoff AND (a.escalation_level IS NULL OR a.escalation_level < 2) "
        "RETURN a.alert_id, a.alert_type, a.subject, a.project, a.person, "
        "a.severity, a.message, a.created_at, coalesce(a.escalation_level, 0)",
        {"cutoff": cutoff},
    )

    escalated: list[dict[str, Any]] = []
    for row in rows:
        alert_id, alert_type, subject, project, person, severity, message, created_at, level = row
        new_severity = _escalate_severity(severity)
        new_level = level + 1
        now = datetime.now(timezone.utc).isoformat()

        await store.query(
            "MATCH (a:Alert {alert_id: $alert_id}) "
            "SET a.severity = $severity, a.escalation_level = $level, "
            "a.escalated_at = $now",
            {"alert_id": alert_id, "severity": new_severity, "level": new_level, "now": now},
        )

        # Create an action so the backend is reminded
        from kgmemory.actions.repository import store_actions

        action = {
            "action": "escalate",
            "target": person or project or subject,
            "message": f"ESCALATED (level {new_level}): {message}",
            "urgency": new_severity,
        }
        await store_actions(store, [action])

        escalated_alert = {
            "alert_id": alert_id,
            "alert_type": alert_type,
            "subject": subject,
            "project": project,
            "person": person,
            "severity": new_severity,
            "message": message,
            "escalation_level": new_level,
            "escalated_at": now,
        }
        escalated.append(escalated_alert)

        if org:
            asyncio.create_task(dispatch_alert_webhook_safe(org, escalated_alert))

    logger.info(f"Escalation for {graph_name}: {len(escalated)} alerts escalated")
    return {
        "graph_name": graph_name,
        "escalated_count": len(escalated),
        "escalated": escalated,
    }


def _escalate_severity(current: str) -> str:
    """Increase severity by one level."""
    current_level = _SEVERITY_ORDER.get(current, 1)
    higher = [label for label, level in _SEVERITY_ORDER.items() if level > current_level]
    return higher[0] if higher else "critical"
