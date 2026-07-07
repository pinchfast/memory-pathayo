from __future__ import annotations

import uuid
from datetime import datetime, timezone

from kgmemory.core.config import settings
from kgmemory.core.logger import logger
from kgmemory.core.metrics import FACTS_INGESTED
from kgmemory.graph.client import get_org_store
from kgmemory.llm.embeddings import get_embedder

from .extraction import extract_facts
from .repository import FactRepository
from .schemas import IngestRequest


async def ingest_message(graph_name: str, payload: IngestRequest) -> dict:
    message = payload.message.strip()[: settings.INGEST_MAX_MESSAGE_CHARS]
    timestamp = payload.timestamp or datetime.now(timezone.utc)
    episode_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"episode:{graph_name}:{payload.session_id}:{payload.speaker}:{timestamp.isoformat()}",
        )
    )
    store = await get_org_store(graph_name)
    repo = FactRepository(store)
    await repo.create_episode(
        episode_id, payload.channel, payload.speaker, payload.session_id, timestamp
    )

    facts, relations, failed_chunks = await extract_facts(
        message,
        speaker=payload.speaker,
        speaker_role=payload.speaker_role.value,
        episode_id=episode_id,
        timestamp=timestamp,
        project=payload.project,
    )

    if facts:
        embeddings = await get_embedder().embed_batch([f.embedding_text for f in facts])
        for fact, embedding in zip(facts, embeddings):
            fact.embedding = embedding

        overrides = await repo.find_duplicate_ids(facts)
        for fact in facts:
            if fact.fact_id in overrides:
                replacement = overrides[fact.fact_id]
                for relation in relations:
                    if relation["from"] == fact.fact_id:
                        relation["from"] = replacement
                    if relation["to"] == fact.fact_id:
                        relation["to"] = replacement
                fact.fact_id = replacement

        invalidated = await repo.supersede_conflicting(facts)
        created = await repo.upsert_facts(facts)
        await repo.link_bridges(facts)
        relations_created = await repo.link_relations(relations)
    else:
        invalidated = created = relations_created = 0

    FACTS_INGESTED.labels(graph_name).inc(created)
    result = {
        "episode_id": episode_id,
        "facts_extracted": len(facts),
        "facts_created": created,
        "facts_invalidated": invalidated,
        "relations_created": relations_created,
        "failed_chunks": failed_chunks,
    }
    logger.info(f"Ingested message into {graph_name}: {result}")
    return result
