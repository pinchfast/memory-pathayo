"""Decision history: store every PM decision as a durable node in the graph
so the system can learn from past outcomes and reference them in future
reasoning."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from kgmemory.graph.client import GraphStore


async def store_decision(store: GraphStore, decision: dict[str, Any]) -> str:
    """Store a PM decision as a DecisionHistory node. Returns the decision_id."""
    now = datetime.now(timezone.utc).isoformat()
    decision_id = hashlib.sha256(
        f"{decision.get('query', '')}:{now}".encode()
    ).hexdigest()[:16]

    await store.query(
        "MERGE (d:DecisionHistory {decision_id: $decision_id}) "
        "SET d.query = $query, d.audience = $audience, d.response_text = $response_text, "
        "d.reasoning = $reasoning, d.risk_level = $risk_level, d.confidence = $confidence, "
        "d.suggested_actions = $suggested_actions, d.outcome = null, "
        "d.outcome_notes = null, d.created_at = $created_at, d.outcome_at = null",
        {
            "decision_id": decision_id,
            "query": decision.get("query", ""),
            "audience": decision.get("audience", ""),
            "response_text": decision.get("response_text", ""),
            "reasoning": decision.get("reasoning", ""),
            "risk_level": decision.get("risk_level", "medium"),
            "confidence": decision.get("confidence", 0.5),
            "suggested_actions": decision.get("suggested_actions") or [],
            "created_at": now,
        },
    )
    return decision_id


async def record_outcome(
    store: GraphStore, decision_id: str, outcome: str, notes: str = ""
) -> dict[str, Any] | None:
    """Record the outcome of a past decision (did the PM's recommendation help?)."""
    now = datetime.now(timezone.utc).isoformat()
    result = await store.query(
        "MATCH (d:DecisionHistory {decision_id: $decision_id}) "
        "SET d.outcome = $outcome, d.outcome_notes = $notes, d.outcome_at = $now "
        "RETURN d.decision_id, d.outcome, d.outcome_notes, d.outcome_at",
        {"decision_id": decision_id, "outcome": outcome, "notes": notes, "now": now},
    )
    if not result:
        return None
    return {
        "decision_id": result[0][0],
        "outcome": result[0][1],
        "outcome_notes": result[0][2],
        "outcome_at": result[0][3],
    }


async def list_decisions(
    store: GraphStore, *, limit: int = 50, with_outcome_only: bool = False
) -> list[dict[str, Any]]:
    where = "WHERE d.outcome IS NOT NULL " if with_outcome_only else ""
    rows = await store.query(
        f"MATCH (d:DecisionHistory) {where}"
        "RETURN d.decision_id, d.query, d.audience, d.risk_level, d.confidence, "
        "d.outcome, d.created_at, d.outcome_at "
        "ORDER BY d.created_at DESC LIMIT $limit",
        {"limit": limit},
    )
    return [
        {
            "decision_id": r[0],
            "query": r[1],
            "audience": r[2],
            "risk_level": r[3],
            "confidence": r[4],
            "outcome": r[5],
            "created_at": r[6],
            "outcome_at": r[7],
        }
        for r in rows
    ]


async def decision_accuracy(store: GraphStore) -> dict[str, Any]:
    """Compute decision accuracy metrics from recorded outcomes."""
    rows = await store.query(
        "MATCH (d:DecisionHistory) WHERE d.outcome IS NOT NULL "
        "RETURN d.outcome, count(d)",
    )
    counts: dict[str, int] = {}
    total = 0
    for row in rows:
        outcome, count = row[0], int(row[1])
        counts[outcome] = count
        total += count
    correct = counts.get("correct", 0) + counts.get("helped", 0)
    accuracy = correct / total if total > 0 else 0.0
    return {
        "total_decisions_with_outcomes": total,
        "outcome_counts": counts,
        "accuracy": round(accuracy, 2),
    }
