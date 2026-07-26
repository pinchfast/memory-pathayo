"""Sprint planning, milestone tracking, retrospectives, and capacity planning.

Sprints are timeboxed iterations (1-2 weeks) with clear goals. The PM plans
what gets done based on team capacity, task dependencies, and priorities.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from kgmemory.core.logger import logger
from kgmemory.graph.client import GraphStore
from kgmemory.llm.client import LLMError, get_llm
from kgmemory.llm.parsing import parse_json_response
from kgmemory.llm.prompts import RETROSPECTIVE_PROMPT, SPRINT_PLANNING_PROMPT
from kgmemory.people.service import list_people
from kgmemory.projects.service import list_tasks


async def create_sprint(
    store: GraphStore,
    project: str,
    goal: str,
    sprint_days: int = 14,
    start_date: str | None = None,
) -> dict[str, Any]:
    """Create a new sprint for a project."""
    sprint_id = f"sprint:{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    start = start_date or now.isoformat()
    end = (now + timedelta(days=sprint_days)).isoformat()

    await store.query(
        "MERGE (p:Project {name: $project}) "
        "CREATE (s:Sprint {sprint_id: $sprint_id, project: $project, goal: $goal, "
        "start_date: $start, end_date: $end, status: 'planning', "
        "created_at: $now}) "
        "MERGE (s)-[:SPRINT_FOR]->(p)",
        {
            "sprint_id": sprint_id,
            "project": project,
            "goal": goal,
            "start": start,
            "end": end,
            "now": now.isoformat(),
        },
    )
    return {
        "sprint_id": sprint_id,
        "project": project,
        "goal": goal,
        "start_date": start,
        "end_date": end,
        "status": "planning",
    }


async def plan_sprint(store: GraphStore, sprint_id: str) -> dict[str, Any]:
    """AI plans what tasks should be in this sprint based on capacity and priorities."""
    started = time.perf_counter()

    # Get sprint info
    sprint_rows = await store.query(
        "MATCH (s:Sprint {sprint_id: $sprint_id}) RETURN s.project, s.goal, "
        "s.start_date, s.end_date, s.status",
        {"sprint_id": sprint_id},
    )
    if not sprint_rows:
        return {"error": "Sprint not found"}
    sprint = sprint_rows[0]
    project, goal, start_str, end_str, status = sprint

    # Calculate sprint days
    try:
        start_dt = datetime.fromisoformat(start_str)
        end_dt = datetime.fromisoformat(end_str)
        sprint_days = (end_dt - start_dt).days
    except (ValueError, TypeError):
        sprint_days = 14

    # Get available tasks for this project
    all_tasks = await list_tasks(store, project=project)
    open_tasks = [t for t in all_tasks if t["status"] == "open"]

    # Get team capacity
    people = await list_people(store)
    total_capacity = sum(
        (p.get("availability_hours_per_week") or 40) for p in people
    )
    # Convert weekly hours to sprint days (rough: 1 day = 8 hours)
    capacity_days = (total_capacity / 8) * (sprint_days / 7)

    # Format tasks for prompt
    tasks_str = "\n".join(
        f"- {t['task_id']}: {t['title']} (est: {t.get('estimated_days') or 'unknown'}d, "
        f"skills: {t.get('required_skills') or []})"
        for t in open_tasks
    ) or "No open tasks"

    team_str = "\n".join(
        f"- {p['name']} ({p['role']}): {p.get('availability_hours_per_week') or 40}h/wk, "
        f"{p.get('open_task_count', 0)} open tasks, reliability {p.get('reliability_score', 0.5)}"
        for p in people
    ) or "No team members"

    prompt = SPRINT_PLANNING_PROMPT.format(
        project=project,
        sprint_days=sprint_days,
        capacity=f"{capacity_days:.0f} person-days",
        tasks=tasks_str,
        team=team_str,
        remaining_work="N/A (new sprint)",
    )

    try:
        response = await get_llm().complete(prompt, kind="sprint_planning", max_tokens=1500)
        payload = parse_json_response(response)
        if not isinstance(payload, dict):
            raise LLMError("Sprint planning payload is not an object")
    except Exception as exc:
        logger.exception(f"Sprint planning LLM failed: {exc}")
        # Fallback: simple capacity-based selection
        total_est = sum(t.get("estimated_days") or 3 for t in open_tasks)
        selected = open_tasks[: max(1, int(capacity_days / 3))]
        payload = {
            "sprint_goal": goal,
            "selected_tasks": [
                {"task_id": t["task_id"], "assignee": t.get("assignee") or "unassigned",
                 "rationale": "Selected based on capacity"}
                for t in selected
            ],
            "deferred_tasks": [
                {"task_id": t["task_id"], "reason": "No capacity"}
                for t in open_tasks[len(selected):]
            ],
            "capacity_utilization": min(1.0, total_est / max(1, capacity_days)),
            "risk_notes": ["LLM planning failed — using simple capacity-based fallback"],
        }

    # Store sprint plan in graph
    for sel in payload.get("selected_tasks") or []:
        task_id = sel.get("task_id")
        if task_id:
            await store.query(
                "MATCH (s:Sprint {sprint_id: $sprint_id}) "
                "MATCH (t:Task {task_id: $task_id}) "
                "MERGE (t)-[:IN_SPRINT]->(s) "
                "SET t.status = 'sprint_planned'",
                {"sprint_id": sprint_id, "task_id": task_id},
            )

    # Update sprint status
    await store.query(
        "MATCH (s:Sprint {sprint_id: $sprint_id}) SET s.status = 'active'",
        {"sprint_id": sprint_id},
    )

    elapsed = int((time.perf_counter() - started) * 1000)
    payload["sprint_id"] = sprint_id
    payload["elapsed_ms"] = elapsed
    return payload


async def get_sprint(store: GraphStore, sprint_id: str) -> dict[str, Any] | None:
    """Get sprint details including tasks."""
    rows = await store.query(
        "MATCH (s:Sprint {sprint_id: $sprint_id}) "
        "RETURN s.sprint_id, s.project, s.goal, s.start_date, s.end_date, s.status",
        {"sprint_id": sprint_id},
    )
    if not rows:
        return None
    r = rows[0]
    tasks = await store.query(
        "MATCH (t:Task)-[:IN_SPRINT]->(s:Sprint {sprint_id: $sprint_id}) "
        "RETURN t.task_id, t.title, t.status, t.estimated_days",
        {"sprint_id": sprint_id},
    )
    return {
        "sprint_id": r[0],
        "project": r[1],
        "goal": r[2],
        "start_date": r[3],
        "end_date": r[4],
        "status": r[5],
        "tasks": [
            {"task_id": t[0], "title": t[1], "status": t[2], "estimated_days": t[3]}
            for t in tasks
        ],
    }


async def list_sprints(store: GraphStore, project: str | None = None) -> list[dict[str, Any]]:
    """List sprints, optionally filtered by project."""
    where = "WHERE s.project = $project " if project else ""
    params: dict[str, Any] = {"project": project} if project else {}
    rows = await store.query(
        f"MATCH (s:Sprint) {where}"
        "RETURN s.sprint_id, s.project, s.goal, s.start_date, s.end_date, s.status "
        "ORDER BY s.start_date DESC",
        params,
    )
    return [
        {
            "sprint_id": r[0],
            "project": r[1],
            "goal": r[2],
            "start_date": r[3],
            "end_date": r[4],
            "status": r[5],
        }
        for r in rows
    ]


async def review_sprint(store: GraphStore, sprint_id: str) -> dict[str, Any]:
    """Run a sprint retrospective — analyze what went well and what didn't."""
    started = time.perf_counter()
    sprint = await get_sprint(store, sprint_id)
    if not sprint:
        return {"error": "Sprint not found"}

    tasks = sprint.get("tasks") or []
    completed = [t for t in tasks if t["status"] == "done"]
    missed = [t for t in tasks if t["status"] != "done"]
    planned = [t["title"] for t in tasks]
    completed_titles = [t["title"] for t in completed]
    missed_titles = [t["title"] for t in missed]

    # Get blockers during sprint period
    blocker_rows = await store.query(
        "MATCH (f:Fact) WHERE f.fact_kind = 'blocker' AND f.temporal_status = 'current' "
        "AND f.valid_from >= $start AND f.valid_from <= $end "
        "RETURN f.value, f.subject",
        {"start": sprint["start_date"], "end": sprint["end_date"]},
    )
    blockers = [r[0] for r in blocker_rows] or ["No blockers recorded"]

    # Get team performance
    people = await list_people(store)
    performance = "\n".join(
        f"- {p['name']}: reliability {p.get('reliability_score', 0.5)}, "
        f"{p.get('completed_count', 0)} completed, {p.get('missed_count', 0)} missed"
        for p in people
    ) or "No team data"

    prompt = RETROSPECTIVE_PROMPT.format(
        sprint_goal=sprint["goal"],
        start_date=sprint["start_date"][:10],
        end_date=sprint["end_date"][:10],
        planned="\n".join(planned) or "No tasks planned",
        completed="\n".join(completed_titles) or "Nothing completed",
        missed="\n".join(missed_titles) or "Nothing missed",
        blockers="\n".join(blockers),
        performance=performance,
    )

    try:
        response = await get_llm().complete(prompt, kind="retro", max_tokens=1500)
        payload = parse_json_response(response)
        if not isinstance(payload, dict):
            raise LLMError("Retrospective payload is not an object")
    except Exception as exc:
        logger.exception(f"Retrospective LLM failed: {exc}")
        verdict = "success" if len(missed) == 0 else "partial" if len(completed) > len(missed) else "failed"
        payload = {
            "what_went_well": [f"Completed {len(completed)} of {len(tasks)} tasks"],
            "what_didnt_go_well": [f"Missed {len(missed)} tasks"] if missed else ["Nothing significant"],
            "what_to_change": ["Review task estimates before next sprint"],
            "lessons_learned": ["Sprint planning should account for dependencies"],
            "sprint_verdict": verdict,
            "team_feedback": {},
        }

    # Store lessons as facts
    for lesson in payload.get("lessons_learned") or []:
        lesson_id = f"fact:{uuid.uuid4().hex[:16]}"
        await store.query(
            "CREATE (f:Fact {fact_id: $fid, subject: $project, predicate: 'learned', "
            "value: $lesson, fact_kind: 'fact', temporal_status: 'current', "
            "valid_from: $now, confidence: 0.7})",
            {
                "fid": lesson_id,
                "project": sprint["project"],
                "lesson": lesson,
                "now": datetime.now(timezone.utc).isoformat(),
            },
        )

    # Update sprint status to completed
    await store.query(
        "MATCH (s:Sprint {sprint_id: $sprint_id}) SET s.status = 'completed'",
        {"sprint_id": sprint_id},
    )

    elapsed = int((time.perf_counter() - started) * 1000)
    payload["sprint_id"] = sprint_id
    payload["elapsed_ms"] = elapsed
    return payload


# --- Milestone tracking (feature 2) ---


async def create_milestone(
    store: GraphStore,
    project: str,
    title: str,
    target_date: str,
    description: str | None = None,
) -> dict[str, Any]:
    """Create a milestone for a project."""
    milestone_id = f"milestone:{uuid.uuid4().hex[:12]}"
    await store.query(
        "MERGE (p:Project {name: $project}) "
        "CREATE (m:Milestone {milestone_id: $mid, project: $project, title: $title, "
        "target_date: $target, description: $desc, status: 'upcoming', created_at: $now}) "
        "MERGE (m)-[:MILESTONE_FOR]->(p)",
        {
            "mid": milestone_id,
            "project": project,
            "title": title,
            "target": target_date,
            "desc": description,
            "now": datetime.now(timezone.utc).isoformat(),
        },
    )
    return {
        "milestone_id": milestone_id,
        "project": project,
        "title": title,
        "target_date": target_date,
        "description": description,
        "status": "upcoming",
    }


async def list_milestones(store: GraphStore, project: str | None = None) -> list[dict[str, Any]]:
    """List milestones, optionally filtered by project."""
    where = "WHERE m.project = $project " if project else ""
    params: dict[str, Any] = {"project": project} if project else {}
    rows = await store.query(
        f"MATCH (m:Milestone) {where}"
        "OPTIONAL MATCH (t:Task)-[:PART_OF]->(p:Project {name: m.project}) "
        "WITH m, collect(t) AS all_tasks "
        "WITH m, all_tasks, size([t IN all_tasks WHERE t.status = 'done']) AS done_count, "
        "size(all_tasks) AS total_count "
        "RETURN m.milestone_id, m.project, m.title, m.target_date, m.description, "
        "m.status, done_count, total_count "
        "ORDER BY m.target_date",
        params,
    )
    now = datetime.now(timezone.utc)
    result = []
    for r in rows:
        target = r[3]
        try:
            target_dt = datetime.fromisoformat(target) if target else None
            if target_dt and now > target_dt and r[5] != "completed":
                status = "overdue"
            else:
                status = r[5] or "upcoming"
        except (ValueError, TypeError):
            status = r[5] or "upcoming"

        total = int(r[7] or 0)
        done = int(r[6] or 0)
        progress = round(done / total, 2) if total > 0 else 0.0
        result.append({
            "milestone_id": r[0],
            "project": r[1],
            "title": r[2],
            "target_date": target,
            "description": r[4],
            "status": status,
            "tasks_done": done,
            "tasks_total": total,
            "progress": progress,
        })
    return result


async def get_roadmap(store: GraphStore, project: str | None = None) -> dict[str, Any]:
    """Generate a roadmap view — milestones and sprints in chronological order."""
    milestones = await list_milestones(store, project)
    sprints = await list_sprints(store, project)

    # Combine and sort by date
    timeline = []
    for m in milestones:
        timeline.append({
            "type": "milestone",
            "date": m.get("target_date"),
            "title": m["title"],
            "project": m["project"],
            "status": m["status"],
            "progress": m["progress"],
        })
    for s in sprints:
        timeline.append({
            "type": "sprint",
            "date": s.get("start_date"),
            "title": s["goal"],
            "project": s["project"],
            "status": s["status"],
        })

    timeline.sort(key=lambda x: x.get("date") or "")

    return {
        "project": project or "all",
        "timeline": timeline,
        "milestone_count": len(milestones),
        "sprint_count": len(sprints),
    }


# --- Capacity planning (feature 6) ---


async def capacity_forecast(
    store: GraphStore, project: str | None = None, weeks: int = 2
) -> dict[str, Any]:
    """Forecast capacity vs. upcoming work. Warn if overcommitted."""
    people = await list_people(store)
    tasks = await list_tasks(store, project=project)
    open_tasks = [t for t in tasks if t["status"] in ("open", "assigned", "sprint_planned")]

    # Total available hours
    total_hours_per_week = sum(
        (p.get("availability_hours_per_week") or 40) for p in people
    )
    total_capacity_hours = total_hours_per_week * weeks

    # Total estimated work (convert days to hours at 8h/day)
    total_estimated_hours = sum(
        (t.get("estimated_days") or 3) * 8 for t in open_tasks
    )

    # Per-person breakdown
    per_person = []
    for p in people:
        weekly_hours = p.get("availability_hours_per_week") or 40
        capacity = weekly_hours * weeks
        # Count their open tasks
        person_tasks = [t for t in open_tasks if t.get("assignee") == p["name"]]
        person_estimated = sum((t.get("estimated_days") or 3) * 8 for t in person_tasks)
        per_person.append({
            "name": p["name"],
            "capacity_hours": capacity,
            "estimated_work_hours": person_estimated,
            "utilization": round(person_estimated / max(1, capacity), 2),
            "overcommitted": person_estimated > capacity * 0.8,
            "open_task_count": len(person_tasks),
        })

    utilization = total_estimated_hours / max(1, total_capacity_hours)
    overcommitted = utilization > 0.8

    # Suggest what to defer
    deferred = []
    if overcommitted:
        # Sort by lowest estimated days (easiest to defer)
        sorted_tasks = sorted(open_tasks, key=lambda t: t.get("estimated_days") or 999, reverse=True)
        excess_hours = total_estimated_hours - total_capacity_hours * 0.8
        deferred_hours = 0
        for t in sorted_tasks:
            if deferred_hours >= excess_hours:
                break
            est = (t.get("estimated_days") or 3) * 8
            deferred.append({"task_id": t["task_id"], "title": t["title"], "estimated_hours": est})
            deferred_hours += est

    return {
        "project": project or "all",
        "forecast_weeks": weeks,
        "total_capacity_hours": total_capacity_hours,
        "total_estimated_hours": total_estimated_hours,
        "utilization": round(utilization, 2),
        "overcommitted": overcommitted,
        "per_person": per_person,
        "suggested_deferrals": deferred,
        "warning": (
            f"Team is overcommitted at {utilization:.0%} utilization. "
            f"Consider deferring {len(deferred)} task(s)."
            if overcommitted else
            "Capacity looks healthy."
        ),
    }
