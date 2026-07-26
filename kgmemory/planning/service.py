"""Scope management, dependency management, estimation tracking, and prioritization.

These are the PM's planning tools — detecting scope creep, managing task
dependencies, tracking estimation accuracy, and prioritizing work.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from kgmemory.core.logger import logger
from kgmemory.graph.client import GraphStore
from kgmemory.llm.client import LLMError, get_llm
from kgmemory.llm.parsing import parse_json_response
from kgmemory.llm.prompts import SCOPE_CREEP_PROMPT
from kgmemory.projects.service import list_tasks


# --- Scope management (feature 4) ---


async def detect_scope_creep(store: GraphStore, project: str) -> dict[str, Any]:
    """Detect scope creep by comparing original requirements to current state."""
    started = time.perf_counter()

    # Get original requirements (from project intake — fact_kind = 'requirement')
    original_rows = await store.query(
        "MATCH (f:Fact) WHERE f.fact_kind = 'requirement' AND f.project = $project "
        "AND f.temporal_status = 'current' "
        "RETURN f.value, f.valid_from ORDER BY f.valid_from",
        {"project": project},
    )
    original_scope = [r[0] for r in original_rows]

    # Get decisions and new requirements added after the original intake
    # (anything added more than 7 days after the first requirement)
    added_rows = await store.query(
        "MATCH (f:Fact) WHERE f.fact_kind IN ['requirement', 'decision'] "
        "AND f.project = $project AND f.temporal_status = 'current' "
        "AND f.valid_from > $cutoff "
        "RETURN f.value, f.fact_kind, f.valid_from ORDER BY f.valid_from",
        {"project": project, "cutoff": _days_ago(7)},
    )
    additions = [{"value": r[0], "kind": r[1], "date": r[2]} for r in added_rows]

    # Get task count
    tasks = await list_tasks(store, project=project)

    # Get project deadline
    proj_rows = await store.query(
        "MATCH (p:Project {name: $project}) RETURN p.deadline, p.description",
        {"project": project},
    )
    deadline = proj_rows[0][0] if proj_rows else None

    prompt = SCOPE_CREEP_PROMPT.format(
        project=project,
        original_scope="\n".join(original_scope) or "No original requirements recorded",
        additions="\n".join(f"- [{a['kind']}] {a['value']}" for a in additions) or "No additions detected",
        start_date="unknown",
        deadline=deadline or "no deadline set",
        task_count=len(tasks),
    )

    try:
        response = await get_llm().complete(prompt, kind="scope", max_tokens=1000)
        payload = parse_json_response(response)
        if not isinstance(payload, dict):
            raise LLMError("Scope creep payload is not an object")
    except Exception as exc:
        logger.exception(f"Scope creep LLM failed: {exc}")
        creep = len(additions) > len(original_scope) * 0.3 if original_scope else len(additions) > 3
        payload = {
            "scope_creep_detected": creep,
            "original_scope_items": len(original_scope),
            "added_items": len(additions),
            "additions": [a["value"] for a in additions],
            "impact_assessment": f"{len(additions)} items added since original scope",
            "recommendation": "review additions" if creep else "no action needed",
            "founder_message": (
                f"Your project '{project}' has grown — {len(additions)} new items "
                f"were added since the original plan. You may want to review if "
                f"the timeline still makes sense."
                if creep else "Project scope looks stable."
            ),
        }

    elapsed = int((time.perf_counter() - started) * 1000)
    payload["project"] = project
    payload["elapsed_ms"] = elapsed
    return payload


# --- Dependency management (feature 5) ---


async def analyze_dependencies(store: GraphStore, project: str | None = None) -> dict[str, Any]:
    """Analyze task dependencies — find chains, critical path, and downstream risks."""
    # Get all blocks/depends_on relations from facts
    rows = await store.query(
        "MATCH (f1:Fact)-[:BLOCKS]->(f2:Fact) "
        "WHERE f1.temporal_status = 'current' AND f2.temporal_status = 'current' "
        + ("AND f1.project = $project " if project else "")
        + "RETURN f1.value, f1.subject, f2.value, f2.subject, f1.project, f1.status",
        {"project": project} if project else {},
    )

    dependencies = []
    for r in rows:
        dependencies.append({
            "blocker": r[0],
            "blocker_owner": r[1],
            "blocked": r[2],
            "blocked_owner": r[3],
            "project": r[4],
        })

    # Get task-level dependencies (from Task nodes if any)
    task_dep_rows = await store.query(
        "MATCH (t1:Task)-[:BLOCKS]->(t2:Task) "
        + ("WHERE t1.project = $project " if project else "")
        + "RETURN t1.task_id, t1.title, t2.task_id, t2.title, t1.status",
        {"project": project} if project else {},
    )
    for r in task_dep_rows:
        dependencies.append({
            "blocker": f"Task: {r[1]}",
            "blocker_owner": "",
            "blocked": f"Task: {r[3]}",
            "blocked_owner": "",
            "project": project or "",
            "task_dependency": True,
            "blocker_status": r[4],
        })

    # Find unresolved blockers (blocker is not a completion)
    unresolved = [
        d for d in dependencies
        if not any(w in d["blocker"].lower() for w in ("completed", "done", "shipped", "resolved"))
    ]

    # Build dependency chains (simple: find chains of 2+)
    chains = _build_chains(dependencies)

    # Critical path: longest chain
    critical_path = max(chains, key=len) if chains else []

    # Downstream risks: blockers that are overdue
    downstream_risks = []
    for dep in unresolved:
        # Check if the blocker has a due date that's passed
        blocker_rows = await store.query(
            "MATCH (f:Fact) WHERE f.value CONTAINS $blocker_text "
            "AND f.fact_kind = 'commitment' AND f.due_date IS NOT NULL "
            "AND f.due_date < $now AND f.temporal_status = 'current' "
            "AND NOT EXISTS { MATCH (f)-[:FULFILLED_BY]->(:Fact) } "
            "RETURN f.value, f.due_date, f.subject",
            {"blocker_text": dep["blocker"][:30], "now": datetime.now(timezone.utc).isoformat()},
        )
        for r in blocker_rows:
            downstream_risks.append({
                "overdue_blocker": r[0],
                "due_date": r[1],
                "owner": r[2],
                "blocked_work": dep["blocked"],
            })

    return {
        "project": project or "all",
        "total_dependencies": len(dependencies),
        "unresolved_blockers": len(unresolved),
        "dependencies": dependencies,
        "dependency_chains": chains,
        "critical_path": critical_path,
        "downstream_risks": downstream_risks,
        "has_risks": len(downstream_risks) > 0,
    }


def _build_chains(dependencies: list[dict[str, Any]]) -> list[list[str]]:
    """Build dependency chains from a list of dependencies."""
    # Simple chain building: A blocks B, B blocks C → [A, B, C]
    chains = []
    for dep in dependencies:
        chain = [dep["blocker"], dep["blocked"]]
        # Try to extend the chain
        changed = True
        while changed:
            changed = False
            for d in dependencies:
                if d["blocker"] == chain[-1] and d["blocked"] not in chain:
                    chain.append(d["blocked"])
                    changed = True
        if len(chain) > 1:
            chains.append(chain)
    # Deduplicate
    seen = set()
    unique = []
    for c in chains:
        key = tuple(c)
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


# --- Estimation tracking (feature 7) ---


async def estimation_accuracy(store: GraphStore, person: str | None = None) -> dict[str, Any]:
    """Track how long engineers say things will take vs. how long they actually take."""
    # Get completed tasks with estimates
    rows = await store.query(
        "MATCH (t:Task) WHERE t.status = 'done' AND t.estimated_days IS NOT NULL "
        + ("AND EXISTS { MATCH (p:Person {name: $name})-[:ASSIGNED_TO]->(t) } " if person else "")
        + "OPTIONAL MATCH (p:Person)-[:ASSIGNED_TO]->(t) "
        + "RETURN t.task_id, t.title, t.estimated_days, t.project, head(collect(p.name))",
        {"name": person} if person else {},
    )

    tasks = []
    for r in rows:
        task_id, title, estimated, project, assignee = r
        # Try to find the actual completion time from facts
        completion_rows = await store.query(
            "MATCH (f:Fact) WHERE f.fact_kind = 'status_update' "
            "AND f.temporal_status = 'current' AND f.value CONTAINS $title "
            "AND f.subject = $assignee "
            "RETURN f.valid_from ORDER BY f.valid_from DESC LIMIT 1",
            {"title": title[:20] if title else "", "assignee": assignee or ""},
        )
        actual_date = completion_rows[0][0] if completion_rows else None

        # Get the task creation date
        creation_rows = await store.query(
            "MATCH (f:Fact) WHERE f.value CONTAINS $title AND f.fact_kind = 'commitment' "
            "RETURN f.valid_from ORDER BY f.valid_from LIMIT 1",
            {"title": title[:20] if title else ""},
        )
        start_date = creation_rows[0][0] if creation_rows else None

        actual_days = None
        if actual_date and start_date:
            try:
                start_dt = datetime.fromisoformat(start_date)
                end_dt = datetime.fromisoformat(actual_date)
                actual_days = (end_dt - start_dt).days
            except (ValueError, TypeError):
                pass

        ratio = None
        if actual_days and estimated:
            ratio = round(actual_days / estimated, 2)

        tasks.append({
            "task_id": task_id,
            "title": title,
            "estimated_days": estimated,
            "actual_days": actual_days,
            "estimation_ratio": ratio,
            "assignee": assignee,
            "project": project,
        })

    # Compute per-person calibration
    calibration = {}
    for t in tasks:
        if t["estimation_ratio"] is not None and t["assignee"]:
            name = t["assignee"]
            if name not in calibration:
                calibration[name] = {"ratios": [], "avg_ratio": 0.0, "tendency": "accurate"}
            calibration[name]["ratios"].append(t["estimation_ratio"])

    for _name, data in calibration.items():
        avg = sum(data["ratios"]) / len(data["ratios"])
        data["avg_ratio"] = round(avg, 2)
        if avg > 1.5:
            data["tendency"] = "underestimates"
        elif avg < 0.7:
            data["tendency"] = "overestimates"
        else:
            data["tendency"] = "accurate"
        del data["ratios"]

    # Overall stats
    all_ratios = [t["estimation_ratio"] for t in tasks if t["estimation_ratio"] is not None]
    overall_avg = round(sum(all_ratios) / len(all_ratios), 2) if all_ratios else None

    return {
        "person": person or "all",
        "total_completed": len(tasks),
        "with_actuals": len([t for t in tasks if t["actual_days"] is not None]),
        "overall_avg_ratio": overall_avg,
        "overall_tendency": (
            "underestimates" if overall_avg and overall_avg > 1.5
            else "overestimates" if overall_avg and overall_avg < 0.7
            else "accurate" if overall_avg else "unknown"
        ),
        "per_person_calibration": calibration,
        "tasks": tasks,
    }


# --- Prioritization (feature 8) ---


async def prioritize_tasks(store: GraphStore, project: str | None = None) -> dict[str, Any]:
    """Rank tasks by business value × urgency × dependency order."""
    tasks = await list_tasks(store, project=project)
    open_tasks = [t for t in tasks if t["status"] in ("open", "assigned", "sprint_planned")]

    # Get dependencies
    deps = await analyze_dependencies(store, project)

    # Score each task
    scored = []
    for task in open_tasks:
        score = 0.0
        reasons = []

        # Urgency: deadline proximity
        if task.get("deadline"):
            try:
                deadline_dt = datetime.fromisoformat(task["deadline"])
                days_until = (deadline_dt - datetime.now(timezone.utc)).days
                if days_until < 0:
                    score += 30  # Overdue — highest priority
                    reasons.append("overdue")
                elif days_until <= 7:
                    score += 20
                    reasons.append("due within 7 days")
                elif days_until <= 14:
                    score += 10
                    reasons.append("due within 2 weeks")
            except (ValueError, TypeError):
                pass

        # Dependency: if other tasks depend on this one, boost it
        for dep in deps.get("dependencies") or []:
            if task["title"] and task["title"][:20] in dep.get("blocker", ""):
                score += 15
                reasons.append("blocks other work")
                break

        # Critical path: if this task is on the critical path
        for chain in deps.get("dependency_chains") or []:
            if task["title"] and any(task["title"][:20] in item for item in chain):
                score += 10
                reasons.append("on critical path")
                break

        # Estimated effort: quick wins get a small boost
        est = task.get("estimated_days") or 3
        if est <= 1:
            score += 5
            reasons.append("quick win")

        # Status: already assigned gets a small boost (momentum)
        if task["status"] == "assigned":
            score += 3
            reasons.append("already assigned")

        scored.append({
            "task_id": task["task_id"],
            "title": task["title"],
            "project": task["project"],
            "priority_score": round(score, 1),
            "reasons": reasons,
            "deadline": task.get("deadline"),
            "estimated_days": est,
            "assignee": task.get("assignee"),
            "status": task["status"],
        })

    # Sort by priority score descending
    scored.sort(key=lambda x: x["priority_score"], reverse=True)

    return {
        "project": project or "all",
        "total_open_tasks": len(open_tasks),
        "prioritized": scored,
        "top_priority": scored[0] if scored else None,
        "recommended_order": [t["task_id"] for t in scored],
    }


def _days_ago(days: int) -> str:
    from datetime import timedelta
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
