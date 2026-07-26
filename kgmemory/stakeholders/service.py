"""Stakeholder communication and budget/burn rate tracking.

Generate tailored updates for different audiences (investors, customers, team,
board) and track project budget consumption and runway.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from kgmemory.core.logger import logger
from kgmemory.graph.client import GraphStore, get_org_store
from kgmemory.llm.client import LLMError, get_llm
from kgmemory.llm.parsing import parse_json_response
from kgmemory.llm.prompts import STAKEHOLDER_UPDATE_PROMPT

from kgmemory.state.repository import latest_person_states, latest_project_states


# --- Stakeholder communication (feature 12) ---


async def generate_stakeholder_update(
    graph_name: str,
    stakeholder_type: str,
    project: str | None = None,
) -> dict[str, Any]:
    """Generate a tailored update for a specific stakeholder audience."""
    started = time.perf_counter()
    store = await get_org_store(graph_name)

    # Get project states
    project_states = await latest_project_states(store)
    if project:
        project_states = [s for s in project_states if s.get("project") == project]

    # Get person states
    person_states = await latest_person_states(store)

    # Get recent wins (fulfilled commitments)
    wins_rows = await store.query(
        "MATCH (c:Fact)-[:FULFILLED_BY]->(s:Fact) "
        "WHERE c.fact_kind = 'commitment' "
        "RETURN c.subject, c.value, c.project "
        "ORDER BY s.valid_from DESC LIMIT 5"
    )
    wins = [f"{r[0]} completed: {r[1]}" for r in wins_rows] or ["No recent wins"]

    # Get recent risks (open alerts)
    from kgmemory.monitor.repository import list_alerts
    alerts = await list_alerts(store, status="open", limit=5)
    risks = [f"[{a.get('severity', 'unknown')}] {a.get('message', '')}" for a in alerts] or ["No active risks"]

    # Get budget info
    budget = await get_budget_status(store, project)

    # Format project states
    project_text = "\n".join(
        f"- {s.get('project')}: {s.get('health')}, {s.get('summary', '')}"
        for s in project_states[:5]
    ) or "No project states available"

    # Key metrics
    metrics = {
        "projects_tracked": len(project_states),
        "people_tracked": len(person_states),
        "recent_completions": len(wins),
        "active_risks": len(risks),
        "budget_utilization": budget.get("utilization_pct", 0),
    }

    prompt = STAKEHOLDER_UPDATE_PROMPT.format(
        stakeholder_type=stakeholder_type,
        project_states=project_text,
        metrics=str(metrics),
        wins="\n".join(wins),
        risks="\n".join(risks),
        budget=f"Utilization: {budget.get('utilization_pct', 0)}%, Runway: {budget.get('runway_weeks', 'unknown')} weeks",
    )

    try:
        response = await get_llm().complete(prompt, kind="stakeholder", max_tokens=1200)
        payload = parse_json_response(response)
        if not isinstance(payload, dict):
            raise LLMError("Stakeholder update payload is not an object")
    except Exception as exc:
        logger.exception(f"Stakeholder update LLM failed: {exc}")
        payload = {
            "update_title": f"{stakeholder_type.title()} Update",
            "update_body": (
                f"Projects: {len(project_states)} tracked, {len(wins)} recent completions, "
                f"{len(risks)} active risks. Budget at {budget.get('utilization_pct', 0)}%."
            ),
            "key_points": [f"{len(project_states)} projects tracked", f"{len(risks)} active risks"],
            "asks": [],
            "tone": "cautious" if risks else "confident",
        }

    elapsed = int((time.perf_counter() - started) * 1000)
    payload["stakeholder_type"] = stakeholder_type
    payload["elapsed_ms"] = elapsed
    return payload


# --- Budget / burn rate tracking (feature 13) ---


async def set_budget(
    store: GraphStore,
    project: str,
    total_budget: float,
    currency: str = "USD",
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Set or update the budget for a project."""
    now = datetime.now(timezone.utc).isoformat()
    await store.query(
        "MERGE (p:Project {name: $project}) "
        "SET p.total_budget = $budget, p.currency = $currency, "
        "p.budget_start = $start, p.budget_end = $end, p.budget_set_at = $now",
        {
            "project": project,
            "budget": total_budget,
            "currency": currency,
            "start": start_date,
            "end": end_date,
            "now": now,
        },
    )
    return {
        "project": project,
        "total_budget": total_budget,
        "currency": currency,
        "start_date": start_date,
        "end_date": end_date,
    }


async def record_spend(
    store: GraphStore,
    project: str,
    amount: float,
    category: str = "general",
    description: str | None = None,
) -> dict[str, Any]:
    """Record a spend against a project budget."""
    import uuid
    spend_id = f"spend:{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    await store.query(
        "MERGE (p:Project {name: $project}) "
        "CREATE (s:Spend {spend_id: $sid, project: $project, amount: $amount, "
        "category: $category, description: $desc, recorded_at: $now}) "
        "MERGE (s)-[:SPEND_FOR]->(p)",
        {
            "sid": spend_id,
            "project": project,
            "amount": amount,
            "category": category,
            "desc": description,
            "now": now,
        },
    )
    return {
        "spend_id": spend_id,
        "project": project,
        "amount": amount,
        "category": category,
        "description": description,
        "recorded_at": now,
    }


async def get_budget_status(store: GraphStore, project: str | None = None) -> dict[str, Any]:
    """Get budget status — total, spent, remaining, utilization, runway."""
    # Get project budget
    proj_rows = await store.query(
        "MATCH (p:Project {name: $project}) "
        "RETURN p.total_budget, p.currency, p.budget_start, p.budget_end",
        {"project": project} if project else {},
    ) if project else await store.query(
        "MATCH (p:Project) WHERE p.total_budget IS NOT NULL "
        "RETURN p.name, p.total_budget, p.currency, p.budget_start, p.budget_end"
    )

    if not proj_rows:
        return {
            "project": project or "all",
            "total_budget": 0,
            "spent": 0,
            "remaining": 0,
            "utilization_pct": 0,
            "runway_weeks": None,
            "warning": "No budget set for this project",
        }

    # Aggregate spend
    if project:
        total_budget = proj_rows[0][0] or 0
        currency = proj_rows[0][1] or "USD"
        budget_start = proj_rows[0][2]
    else:
        total_budget = sum(r[1] or 0 for r in proj_rows)
        currency = proj_rows[0][2] or "USD"
        budget_start = min((r[3] for r in proj_rows if r[3]), default=None)

    # Get total spend
    spend_rows = await store.query(
        "MATCH (s:Spend) " + ("WHERE s.project = $project " if project else "")
        + "RETURN sum(s.amount), count(s)",
        {"project": project} if project else {},
    )
    total_spent = float(spend_rows[0][0] or 0) if spend_rows else 0
    spend_count = int(spend_rows[0][1] or 0) if spend_rows else 0

    remaining = total_budget - total_spent
    utilization_pct = round((total_spent / total_budget * 100), 1) if total_budget > 0 else 0

    # Calculate runway (how many weeks until budget runs out)
    runway_weeks = None
    if budget_start and total_spent > 0:
        try:
            start_dt = datetime.fromisoformat(budget_start)
            now = datetime.now(timezone.utc)
            elapsed_days = max(1, (now - start_dt).days)
            burn_rate_per_day = total_spent / elapsed_days
            if burn_rate_per_day > 0 and remaining > 0:
                runway_days = remaining / burn_rate_per_day
                runway_weeks = round(runway_days / 7, 1)
        except (ValueError, TypeError):
            pass

    # Warning levels
    if utilization_pct >= 90:
        warning = "CRITICAL: Budget nearly exhausted"
    elif utilization_pct >= 75:
        warning = "WARNING: Budget over 75% spent"
    elif utilization_pct >= 50:
        warning = "Budget at halfway point"
    else:
        warning = "Budget healthy"

    # Spend by category
    category_rows = await store.query(
        "MATCH (s:Spend) " + ("WHERE s.project = $project " if project else "")
        + "RETURN s.category, sum(s.amount) ORDER BY sum(s.amount) DESC",
        {"project": project} if project else {},
    )
    by_category = {r[0] or "general": float(r[1]) for r in category_rows}

    return {
        "project": project or "all",
        "total_budget": total_budget,
        "currency": currency,
        "spent": round(total_spent, 2),
        "remaining": round(remaining, 2),
        "utilization_pct": utilization_pct,
        "runway_weeks": runway_weeks,
        "spend_count": spend_count,
        "by_category": by_category,
        "warning": warning,
    }
