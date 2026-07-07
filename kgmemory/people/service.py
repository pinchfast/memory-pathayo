from __future__ import annotations

from typing import Any

from kgmemory.graph.client import GraphStore, get_org_store


async def upsert_person(store: GraphStore, person: dict[str, Any]) -> None:
    await store.query(
        "MERGE (p:Person {name: $name}) "
        "SET p.role = $role, p.title = $title, p.skills = $skills, "
        "p.languages = $languages, p.is_technical = $is_technical, p.person_id = $name",
        {
            "name": person["name"].strip().lower(),
            "role": person["role"],
            "title": person.get("title"),
            "skills": [s.strip().lower() for s in person.get("skills") or []],
            "languages": person.get("languages") or [],
            "is_technical": person.get("is_technical", False),
        },
    )


async def get_person(store: GraphStore, name: str) -> dict[str, Any] | None:
    rows = await store.query(
        "MATCH (p:Person {name: $name}) "
        "RETURN p.name, p.role, p.title, p.skills, p.languages, p.is_technical",
        {"name": name.strip().lower()},
    )
    if not rows:
        return None
    row = rows[0]
    facts = await store.query(
        "MATCH (p:Person {name: $name})-[:STATED]->(f:Fact) "
        "WHERE f.temporal_status = 'current' "
        "RETURN f.fact_id, f.fact_kind, f.subject, f.predicate, f.value, f.valid_from "
        "ORDER BY f.valid_from DESC LIMIT 50",
        {"name": name.strip().lower()},
    )
    reliability = await compute_reliability(store, name)
    return {
        "name": row[0],
        "role": row[1],
        "title": row[2],
        "skills": row[3] or [],
        "languages": row[4] or [],
        "is_technical": bool(row[5]),
        "facts": [
            {
                "fact_id": r[0],
                "fact_kind": r[1],
                "subject": r[2],
                "predicate": r[3],
                "value": r[4],
                "valid_from": r[5],
            }
            for r in facts
        ],
        "reliability": reliability,
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
        "MATCH (p:Person) RETURN p.name, p.role, p.title, p.skills ORDER BY p.name"
    )
    summaries = []
    for row in rows:
        name, role, title, skills = row
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
            }
        )
    return summaries


async def get_store(graph_name: str) -> GraphStore:
    return await get_org_store(graph_name)
