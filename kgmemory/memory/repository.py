from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from kgmemory.core.config import settings
from kgmemory.graph.client import GraphStore

from .schemas import SINGLE_VALUE_KINDS, Fact, FactKind, TemporalStatus

FACT_RETURN = (
    "f.fact_id, f.subject, f.predicate, f.value, f.fact_kind, f.topics, f.entities, "
    "f.project, f.task, f.sentiment, f.temporal_status, f.valid_from, f.speaker, f.due_date"
)


def row_to_fact_dict(row: list[Any]) -> dict[str, Any]:
    return {
        "fact_id": row[0],
        "subject": row[1],
        "predicate": row[2],
        "value": row[3],
        "fact_kind": row[4],
        "topics": row[5] or [],
        "entities": row[6] or [],
        "project": row[7],
        "task": row[8],
        "sentiment": row[9] or "neutral",
        "temporal_status": row[10] or "current",
        "valid_from": row[11],
        "speaker": row[12],
        "due_date": row[13],
    }


class FactRepository:
    def __init__(self, store: GraphStore):
        self.store = store

    async def find_duplicate_ids(self, facts: list[Fact]) -> dict[str, str]:
        """Map new fact_ids to existing near-duplicate fact_ids (cosine dedup)."""
        overrides: dict[str, str] = {}
        for fact in facts:
            if fact.embedding is None:
                continue
            rows = await self.store.query(
                "CALL db.idx.vector.queryNodes('Fact', 'embedding', 1, vecf32($vector)) "
                "YIELD node, score "
                "WHERE node.temporal_status = 'current' AND score <= $max_distance "
                "RETURN node.fact_id",
                {
                    "vector": fact.embedding,
                    "max_distance": 1.0 - settings.INGEST_DEDUP_SIMILARITY,
                },
            )
            if rows and rows[0][0] != fact.fact_id:
                overrides[fact.fact_id] = rows[0][0]
        return overrides

    async def supersede_conflicting(self, facts: list[Fact]) -> int:
        rows = [
            {
                "new_fact_id": f.fact_id,
                "subject": f.subject.strip().lower(),
                "predicate": f.predicate.strip().lower(),
                "new_value": f.value.strip().lower(),
            }
            for f in facts
            if f.fact_kind in SINGLE_VALUE_KINDS
        ]
        if not rows:
            return 0
        result = await self.store.query(
            "UNWIND $rows AS row "
            "MATCH (f:Fact) "
            "WHERE f.temporal_status = 'current' AND f.fact_id <> row.new_fact_id "
            "AND toLower(f.subject) = row.subject AND toLower(f.predicate) = row.predicate "
            "AND toLower(f.value) <> row.new_value "
            "SET f.temporal_status = 'superseded', f.valid_until = $now, "
            "f.superseded_by = row.new_fact_id "
            "RETURN count(f)",
            {"rows": rows, "now": _iso_now()},
        )
        return int(result[0][0]) if result else 0

    async def upsert_facts(self, facts: list[Fact]) -> int:
        if not facts:
            return 0
        rows = [
            {
                "fact_id": f.fact_id,
                "subject": f.subject,
                "predicate": f.predicate,
                "value": f.value,
                "fact_kind": f.fact_kind.value,
                "topics": f.topics,
                "entities": f.entities,
                "project": f.project,
                "task": f.task,
                "numeric_value": f.numeric_value,
                "unit": f.unit,
                "sentiment": f.sentiment,
                "temporal_hint": f.temporal_hint,
                "due_date": f.due_date,
                "evidence_quote": f.evidence_quote,
                "speaker": f.speaker,
                "speaker_role": f.speaker_role.value,
                "episode_id": f.episode_id,
                "temporal_status": f.temporal_status.value,
                "valid_from": f.valid_from.isoformat(),
            }
            for f in facts
        ]
        result = await self.store.query(
            "UNWIND $rows AS row "
            "MERGE (f:Fact {fact_id: row.fact_id}) "
            "SET f.subject = row.subject, f.predicate = row.predicate, f.value = row.value, "
            "f.fact_kind = row.fact_kind, f.topics = row.topics, f.entities = row.entities, "
            "f.project = row.project, f.task = row.task, f.numeric_value = row.numeric_value, "
            "f.unit = row.unit, f.sentiment = row.sentiment, f.temporal_hint = row.temporal_hint, "
            "f.due_date = row.due_date, f.evidence_quote = row.evidence_quote, "
            "f.speaker = row.speaker, f.speaker_role = row.speaker_role, "
            "f.episode_id = row.episode_id, f.temporal_status = row.temporal_status, "
            "f.valid_from = row.valid_from "
            "RETURN count(f)",
            {"rows": rows},
        )
        for fact in facts:
            if fact.embedding is not None:
                await self.store.query(
                    "MATCH (f:Fact {fact_id: $fact_id}) SET f.embedding = vecf32($vector)",
                    {"fact_id": fact.fact_id, "vector": fact.embedding},
                )
        return int(result[0][0]) if result else 0

    async def link_bridges(self, facts: list[Fact]) -> None:
        topic_rows, entity_rows, person_rows, project_rows, task_rows, episode_rows = (
            [], [], [], [], [], [],
        )
        for f in facts:
            topic_rows += [{"fact_id": f.fact_id, "name": t} for t in f.topics]
            entity_rows += [{"fact_id": f.fact_id, "name": e.strip().lower()} for e in f.entities]
            if f.speaker:
                person_rows.append({
                    "fact_id": f.fact_id,
                    "name": f.speaker.strip().lower(),
                    "role": f.speaker_role.value,
                })
            if f.project:
                project_rows.append({"fact_id": f.fact_id, "name": f.project.strip()})
            if f.task and f.project:
                task_rows.append({"fact_id": f.fact_id, "name": f.task.strip(), "project": f.project.strip()})
            if f.episode_id:
                episode_rows.append({"fact_id": f.fact_id, "episode_id": f.episode_id})
        statements = [
            (
                "UNWIND $rows AS row MATCH (f:Fact {fact_id: row.fact_id}) "
                "MERGE (t:Topic {name: row.name}) MERGE (f)-[:ABOUT]->(t)",
                topic_rows,
            ),
            (
                "UNWIND $rows AS row MATCH (f:Fact {fact_id: row.fact_id}) "
                "MERGE (e:Entity {name: row.name}) MERGE (f)-[:MENTIONS]->(e)",
                entity_rows,
            ),
            (
                "UNWIND $rows AS row MATCH (f:Fact {fact_id: row.fact_id}) "
                "MERGE (p:Person {name: row.name}) ON CREATE SET p.person_id = row.name, p.role = row.role "
                "MERGE (p)-[:STATED]->(f)",
                person_rows,
            ),
            (
                "UNWIND $rows AS row MATCH (f:Fact {fact_id: row.fact_id}) "
                "MERGE (pr:Project {name: row.name}) ON CREATE SET pr.project_id = row.name, pr.status = 'active' "
                "MERGE (f)-[:ABOUT_PROJECT]->(pr)",
                project_rows,
            ),
            (
                "UNWIND $rows AS row MATCH (f:Fact {fact_id: row.fact_id}) "
                "MERGE (pr:Project {name: row.project}) "
                "MERGE (t:Task {task_id: row.project + ':' + row.name}) "
                "ON CREATE SET t.name = row.name, t.status = 'open' "
                "MERGE (t)-[:PART_OF]->(pr) MERGE (f)-[:ABOUT_TASK]->(t)",
                task_rows,
            ),
            (
                "UNWIND $rows AS row MATCH (f:Fact {fact_id: row.fact_id}) "
                "MATCH (ep:Episode {episode_id: row.episode_id}) MERGE (f)-[:SAID_IN]->(ep)",
                episode_rows,
            ),
        ]
        for cypher, rows in statements:
            if rows:
                await self.store.query(cypher, {"rows": rows})

    async def link_relations(self, relations: list[dict[str, str]]) -> int:
        created = 0
        for relation_type in ("causes", "influences", "blocks", "depends_on"):
            rows = [r for r in relations if r.get("type") == relation_type]
            if not rows:
                continue
            result = await self.store.query(
                "UNWIND $rows AS row "
                "MATCH (src:Fact {fact_id: row.from}) MATCH (tgt:Fact {fact_id: row.to}) "
                f"MERGE (src)-[:{relation_type.upper()}]->(tgt) RETURN count(src)",
                {"rows": rows},
            )
            created += int(result[0][0]) if result else 0
        return created

    async def create_episode(
        self, episode_id: str, channel: str, speaker: str, session_id: str | None, occurred_at: datetime
    ) -> None:
        await self.store.query(
            "MERGE (ep:Episode {episode_id: $episode_id}) "
            "SET ep.channel = $channel, ep.speaker = $speaker, ep.session_id = $session_id, "
            "ep.occurred_at = $occurred_at",
            {
                "episode_id": episode_id,
                "channel": channel,
                "speaker": speaker,
                "session_id": session_id,
                "occurred_at": occurred_at.isoformat(),
            },
        )

    async def list_facts(
        self,
        *,
        subject: str | None = None,
        topic: str | None = None,
        project: str | None = None,
        fact_kind: str | None = None,
        current_only: bool = True,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        conditions, params = [], {"limit": limit}
        if current_only:
            conditions.append("f.temporal_status = 'current'")
        if subject:
            conditions.append("toLower(f.subject) CONTAINS $subject")
            params["subject"] = subject.strip().lower()
        if topic:
            conditions.append("$topic IN f.topics")
            params["topic"] = topic.strip().lower()
        if project:
            conditions.append("toLower(f.project) = $project")
            params["project"] = project.strip().lower()
        if fact_kind:
            conditions.append("f.fact_kind = $fact_kind")
            params["fact_kind"] = fact_kind
        where = f"WHERE {' AND '.join(conditions)} " if conditions else ""
        rows = await self.store.query(
            f"MATCH (f:Fact) {where}RETURN {FACT_RETURN} "
            "ORDER BY f.valid_from DESC LIMIT $limit",
            params,
        )
        return [row_to_fact_dict(row) for row in rows]

    async def invalidate_fact(self, fact_id: str) -> bool:
        rows = await self.store.query(
            "MATCH (f:Fact {fact_id: $fact_id}) "
            "SET f.temporal_status = 'invalidated', f.valid_until = $now RETURN count(f)",
            {"fact_id": fact_id, "now": _iso_now()},
        )
        return bool(rows and rows[0][0])

    async def vector_search(self, embedding: list[float], top_k: int) -> list[dict[str, Any]]:
        rows = await self.store.query(
            "CALL db.idx.vector.queryNodes('Fact', 'embedding', $k, vecf32($vector)) "
            "YIELD node, score "
            "WHERE node.temporal_status = 'current' "
            "WITH node AS f, score "
            f"RETURN {FACT_RETURN}, score",
            {"vector": embedding, "k": top_k},
        )
        results = []
        for row in rows:
            fact = row_to_fact_dict(row[:-1])
            fact["similarity"] = 1.0 - float(row[-1])
            results.append(fact)
        return results

    async def traverse(
        self, topics: list[str], entities: list[str], max_hops: int, limit: int = 100
    ) -> list[dict[str, Any]]:
        if not topics and not entities:
            return []
        rows = await self.store.query(
            "MATCH (seed) WHERE (seed:Topic AND seed.name IN $topics) "
            "OR (seed:Entity AND seed.name IN $entities) "
            f"MATCH (seed)<-[:ABOUT|MENTIONS*1..{max_hops}]-(f:Fact) "
            "WHERE f.temporal_status = 'current' "
            f"WITH DISTINCT f RETURN {FACT_RETURN} LIMIT $limit",
            {
                "topics": topics,
                "entities": [e.strip().lower() for e in entities],
                "limit": limit,
            },
        )
        return [row_to_fact_dict(row) for row in rows]

    async def recent_facts(self, limit: int = 40) -> list[dict[str, Any]]:
        rows = await self.store.query(
            f"MATCH (f:Fact) WHERE f.temporal_status = 'current' RETURN {FACT_RETURN} "
            "ORDER BY f.valid_from DESC LIMIT $limit",
            {"limit": limit},
        )
        return [row_to_fact_dict(row) for row in rows]

    async def counts(self) -> dict[str, int]:
        labels = ("Fact", "Person", "Project", "Task", "Episode")
        counts = {}
        for label in labels:
            rows = await self.store.query(f"MATCH (n:{label}) RETURN count(n)")
            counts[label.lower() + "s"] = int(rows[0][0]) if rows else 0
        return counts


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_fact_from_raw(
    raw: dict[str, Any],
    *,
    speaker: str,
    speaker_role: str,
    episode_id: str,
    timestamp: datetime,
    project: str | None,
) -> Fact | None:
    subject = str(raw.get("subject") or "").strip()
    predicate = str(raw.get("predicate") or "").strip()
    value = str(raw.get("value") or "").strip()
    if not (subject and predicate and value):
        return None
    try:
        kind = FactKind(str(raw.get("fact_kind") or "fact"))
    except ValueError:
        kind = FactKind.FACT
    return Fact(
        subject=subject,
        predicate=predicate,
        value=value,
        fact_kind=kind,
        topics=[str(t) for t in raw.get("topics") or []],
        entities=[str(e) for e in raw.get("entities") or []],
        project=raw.get("project") or project,
        task=raw.get("task"),
        numeric_value=raw.get("numeric_value"),
        unit=raw.get("unit"),
        sentiment=str(raw.get("sentiment") or "neutral"),
        temporal_hint=str(raw.get("temporal_hint") or "current"),
        due_date=raw.get("due_date"),
        evidence_quote=raw.get("evidence_quote"),
        speaker=speaker,
        speaker_role=speaker_role,
        episode_id=episode_id,
        temporal_status=TemporalStatus.CURRENT,
        valid_from=timestamp,
    )
