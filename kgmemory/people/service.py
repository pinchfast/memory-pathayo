from __future__ import annotations

from typing import Any

from kgmemory.graph.client import GraphStore, get_org_store


async def upsert_person(store: GraphStore, person: dict[str, Any]) -> None:
    await store.query(
        "MERGE (p:Person {name: $name}) "
        "SET p.role = $role, p.title = $title, p.skills = $skills, "
        "p.languages = $languages, p.is_technical = $is_technical, p.person_id = $name, "
        "p.experience_years = $experience_years, "
        "p.availability_hours_per_week = $availability_hours_per_week, "
        "p.timezone = $timezone, p.interests = $interests, "
        "p.career_goals = $career_goals, p.resume_summary = $resume_summary",
        {
            "name": person["name"].strip().lower(),
            "role": person["role"],
            "title": person.get("title"),
            "skills": [s.strip().lower() for s in person.get("skills") or []],
            "languages": person.get("languages") or [],
            "is_technical": person.get("is_technical", False),
            "experience_years": person.get("experience_years"),
            "availability_hours_per_week": person.get("availability_hours_per_week"),
            "timezone": person.get("timezone"),
            "interests": person.get("interests") or [],
            "career_goals": person.get("career_goals"),
            "resume_summary": person.get("resume_summary"),
        },
    )


async def get_person(store: GraphStore, name: str) -> dict[str, Any] | None:
    rows = await store.query(
        "MATCH (p:Person {name: $name}) "
        "RETURN p.name, p.role, p.title, p.skills, p.languages, p.is_technical, "
        "p.experience_years, p.availability_hours_per_week, p.timezone, "
        "p.interests, p.career_goals, p.resume_summary",
        {"name": name.strip().lower()},
    )
    if not rows:
        return None
    row = rows[0]
    facts = await store.query(
        "MATCH (p:Person {name: $name})-[:STATED]->(f:Fact) "
        "WHERE f.temporal_status = 'current' "
        "RETURN f.fact_id, f.fact_kind, f.subject, f.predicate, f.value, f.valid_from, f.project "
        "ORDER BY f.valid_from DESC LIMIT 50",
        {"name": name.strip().lower()},
    )
    reliability = await compute_reliability(store, name)
    contributions = await get_contributions(store, name)
    return {
        "name": row[0],
        "role": row[1],
        "title": row[2],
        "skills": row[3] or [],
        "languages": row[4] or [],
        "is_technical": bool(row[5]),
        "experience_years": row[6],
        "availability_hours_per_week": row[7],
        "timezone": row[8],
        "interests": row[9] or [],
        "career_goals": row[10],
        "resume_summary": row[11],
        "facts": [
            {
                "fact_id": r[0],
                "fact_kind": r[1],
                "subject": r[2],
                "predicate": r[3],
                "value": r[4],
                "valid_from": r[5],
                "project": r[6],
            }
            for r in facts
        ],
        "reliability": reliability,
        "contributions": contributions,
    }


async def compute_reliability(store: GraphStore, name: str) -> dict[str, Any]:
    rows = await store.query(
        "MATCH (p:Person {name: $name})-[:STATED]->(f:Fact) "
        "WHERE f.temporal_status = 'current' AND f.fact_kind IN $kinds "
        "RETURN f.fact_kind, count(f)",
        {"name": name.strip().lower(), "kinds": ["commitment", "status_update", "performance"]},
    )
    counts = {row[0]: int(row[1]) for row in rows}
    commitments = counts.get("commitment", 0)
    completed = counts.get("status_update", 0)
    missed = counts.get("performance", 0)
    total = commitments + completed + missed
    if total == 0:
        score = 0.5
    else:
        score = max(0.0, min(1.0, (completed + 0.5 * commitments - 2 * missed) / total))
    return {
        "commitments": commitments,
        "completed": completed,
        "missed_or_flagged": missed,
        "reliability_score": round(score, 2),
    }


async def list_people(store: GraphStore) -> list[dict[str, Any]]:
    rows = await store.query(
        "MATCH (p:Person) "
        "RETURN p.name, p.role, p.title, p.skills, p.availability_hours_per_week "
        "ORDER BY p.name"
    )
    summaries = []
    for row in rows:
        name, role, title, skills, availability = row
        reliability = await compute_reliability(store, name)
        summaries.append(
            {
                "name": name,
                "role": role,
                "title": title,
                "skill_count": len(skills or []),
                "commitment_count": reliability["commitments"],
                "completed_count": reliability["completed"],
                "missed_count": reliability["missed_or_flagged"],
                "reliability_score": reliability["reliability_score"],
                "availability_hours_per_week": availability,
                "is_available": availability is None or availability > 0,
            }
        )
    return summaries


async def get_contributions(store: GraphStore, name: str) -> dict[str, Any]:
    """Build a contribution profile for a person — what they've done over time,
    grouped by project and fact kind, with a timeline of recent activity.
    """
    # Aggregate by fact kind
    kind_rows = await store.query(
        "MATCH (p:Person {name: $name})-[:STATED]->(f:Fact) "
        "WHERE f.temporal_status = 'current' "
        "RETURN f.fact_kind, count(f) ORDER BY count(f) DESC",
        {"name": name.strip().lower()},
    )
    by_kind = {row[0]: int(row[1]) for row in kind_rows}

    # Aggregate by project
    project_rows = await store.query(
        "MATCH (p:Person {name: $name})-[:STATED]->(f:Fact) "
        "WHERE f.temporal_status = 'current' AND f.project IS NOT NULL "
        "RETURN f.project, count(f) ORDER BY count(f) DESC",
        {"name": name.strip().lower()},
    )
    by_project = {row[0]: int(row[1]) for row in project_rows}

    # Recent timeline (last 20 facts with dates)
    timeline_rows = await store.query(
        "MATCH (p:Person {name: $name})-[:STATED]->(f:Fact) "
        "WHERE f.temporal_status = 'current' "
        "RETURN f.fact_kind, f.value, f.valid_from, f.project "
        "ORDER BY f.valid_from DESC LIMIT 20",
        {"name": name.strip().lower()},
    )
    timeline = [
        {
            "fact_kind": r[0],
            "value": r[1],
            "date": r[2],
            "project": r[3],
        }
        for r in timeline_rows
    ]

    # Count fulfilled commitments (work actually delivered)
    fulfilled_rows = await store.query(
        "MATCH (p:Person {name: $name})-[:STATED]->(c:Fact) "
        "WHERE c.fact_kind = 'commitment' AND EXISTS { MATCH (c)-[:FULFILLED_BY]->(:Fact) } "
        "RETURN count(c)",
        {"name": name.strip().lower()},
    )
    fulfilled_count = int(fulfilled_rows[0][0]) if fulfilled_rows else 0

    return {
        "total_facts": sum(by_kind.values()),
        "by_kind": by_kind,
        "by_project": by_project,
        "fulfilled_commitments": fulfilled_count,
        "timeline": timeline,
    }


async def get_store(graph_name: str) -> GraphStore:
    return await get_org_store(graph_name)
