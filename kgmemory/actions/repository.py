"""Action queue: durable storage for PM-suggested actions.

When /pm/decide returns suggested_actions, they're persisted as Action nodes
in the graph so the Django backend can fetch and execute them (Slack pings,
escalations, etc.) and mark them complete. This closes the autonomy loop:
detect risk → decide → queue action → backend executes → mark done.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from kgmemory.graph.client import GraphStore


async def store_actions(store: GraphStore, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Store suggested actions as Action nodes. Returns the created/updated actions."""
    if not actions:
        return []
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for i, action in enumerate(actions):
        action_id = f"action:{now}:{i}:{action.get('action', 'none')}:{action.get('target', '')}"
        rows.append({
            "action_id": action_id,
            "action": action.get("action", "none"),
            "target": action.get("target", ""),
            "message": action.get("message", ""),
            "urgency": action.get("urgency", "low"),
            "status": "pending",
            "created_at": now,
        })

    await store.query(
        "UNWIND $rows AS row "
        "MERGE (a:Action {action_id: row.action_id}) "
        "SET a.action = row.action, a.target = row.target, a.message = row.message, "
        "a.urgency = row.urgency, a.status = row.status, a.created_at = row.created_at",
        {"rows": rows},
    )
    return rows


async def list_actions(
    store: GraphStore, *, status: str = "pending", limit: int = 50
) -> list[dict[str, Any]]:
    query = "MATCH (a:Action) "
    params: dict[str, Any] = {"limit": limit}
    if status != "all":
        query += "WHERE a.status = $status "
        params["status"] = status
    query += (
        "RETURN a.action_id, a.action, a.target, a.message, a.urgency, "
        "a.status, a.created_at, a.completed_at "
        "ORDER BY a.created_at DESC LIMIT $limit"
    )
    rows = await store.query(query, params)
    return [
        {
            "action_id": r[0],
            "action": r[1],
            "target": r[2],
            "message": r[3],
            "urgency": r[4],
            "status": r[5],
            "created_at": r[6],
            "completed_at": r[7],
        }
        for r in rows
    ]


async def complete_action(store: GraphStore, action_id: str) -> dict[str, Any] | None:
    now = datetime.now(timezone.utc).isoformat()
    result = await store.query(
        "MATCH (a:Action {action_id: $action_id}) "
        "WHERE a.status = 'pending' "
        "SET a.status = 'completed', a.completed_at = $now "
        "RETURN a.action_id, a.status, a.completed_at",
        {"action_id": action_id, "now": now},
    )
    if not result:
        return None
    return {
        "action_id": result[0][0],
        "status": result[0][1],
        "completed_at": result[0][2],
    }
