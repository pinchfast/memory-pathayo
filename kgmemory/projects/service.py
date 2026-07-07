from __future__ import annotations

from typing import Any

from kgmemory.graph.client import GraphStore, get_org_store


async def upsert_project(store: GraphStore, project: dict[str, Any]) -> None:
    await store.query(
        "MERGE (p:Project {name: $name}) "
        "SET p.description = $description, p.status = $status, p.deadline = $deadline",
        {
            "name": project["name"].strip(),
            "description": project.get("description"),
            "status": project["status"],
            "deadline": project.get("deadline"),
        },
    )


async def list_projects(store: GraphStore) -> list[dict[str, Any]]:
    rows = await store.query(
        "MATCH (p:Project) "
        "OPTIONAL MATCH (p)<-[:PART_OF]-(t:Task) "
        "OPTIONAL MATCH (p)<-[:ABOUT_PROJECT]-(f:Fact) "
        "WITH p, collect(DISTINCT t) AS tasks, collect(DISTINCT f) AS facts "
        "RETURN p.name, p.description, p.status, p.deadline, "
        "size(tasks), size([t IN tasks WHERE t.status <> 'done']), size(facts)"
    )
    return [
        {
            "name": r[0],
            "description": r[1],
            "status": r[2],
            "deadline": r[3],
            "task_count": int(r[4] or 0),
            "open_task_count": int(r[5] or 0),
            "member_count": 0,
        }
        for r in rows
    ]


async def upsert_task(store: GraphStore, task: dict[str, Any]) -> str:
    task_id = f"{task['project'].strip()}:{task['title'].strip()}"
    await store.query(
        "MERGE (p:Project {name: $project}) "
        "MERGE (t:Task {task_id: $task_id}) "
        "SET t.title = $title, t.description = $description, "
        "t.required_skills = $required_skills, t.estimated_days = $estimated_days, "
        "t.deadline = $deadline, t.status = coalesce(t.status, 'open') "
        "MERGE (t)-[:PART_OF]->(p)",
        {
            "project": task["project"].strip(),
            "task_id": task_id,
            "title": task["title"],
            "description": task.get("description"),
            "required_skills": [s.strip().lower() for s in task.get("required_skills") or []],
            "estimated_days": task.get("estimated_days"),
            "deadline": task.get("deadline"),
        },
    )
    return task_id


async def list_tasks(store: GraphStore, project: str | None = None) -> list[dict[str, Any]]:
    where = "WHERE t.project = $project " if project else ""
    params: dict[str, Any] = {"project": project} if project else {}
    rows = await store.query(
        "MATCH (t:Task)<-[:PART_OF]-(p:Project) "
        f"{where}"
        "OPTIONAL MATCH (person:Person)-[:ASSIGNED_TO]->(t) "
        "WITH t, p, collect(person.name) AS assignees "
        "RETURN t.task_id, t.title, p.name, t.status, t.required_skills, "
        "t.estimated_days, t.deadline, head(assignees)",
        params,
    )
    return [
        {
            "task_id": r[0],
            "title": r[1],
            "project": r[2],
            "status": r[3] or "open",
            "required_skills": r[4] or [],
            "estimated_days": r[5],
            "deadline": r[6],
            "assignee": r[7],
        }
        for r in rows
    ]


async def recommend_assignees(store: GraphStore, task_id: str) -> list[dict[str, Any]]:
    rows = await store.query(
        "MATCH (t:Task {task_id: $task_id}) RETURN t.required_skills",
        {"task_id": task_id},
    )
    if not rows:
        return []
    required = [s.lower() for s in rows[0][0] or []]
    if not required:
        return []
    people = await store.query(
        "MATCH (p:Person) RETURN p.name, p.skills, p.role"
    )
    recommendations = []
    for name, skills, role in people:
        skill_set = {s.lower() for s in skills or []}
        matched = set(required) & skill_set
        if not matched:
            continue
        coverage = len(matched) / len(required)
        recommendations.append(
            {
                "person": name,
                "role": role,
                "matched_skills": sorted(matched),
                "missing_skills": sorted(set(required) - skill_set),
                "coverage": round(coverage, 2),
            }
        )
    recommendations.sort(key=lambda r: r["coverage"], reverse=True)
    return recommendations


async def assign_task(store: GraphStore, task_id: str, person_name: str) -> None:
    await store.query(
        "MATCH (t:Task {task_id: $task_id}) "
        "MATCH (p:Person {name: $name}) "
        "MERGE (p)-[:ASSIGNED_TO]->(t) "
        "SET t.status = 'assigned'",
        {"task_id": task_id, "name": person_name.strip().lower()},
    )


async def get_store(graph_name: str) -> GraphStore:
    return await get_org_store(graph_name)
