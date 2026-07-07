from kgmemory.core.config import settings
from kgmemory.core.logger import logger

from .client import GraphStore

NODE_INDEXES: dict[str, list[str]] = {
    "Person": ["person_id", "name"],
    "Project": ["project_id", "name", "status"],
    "Task": ["task_id", "status"],
    "Fact": [
        "fact_id",
        "subject",
        "predicate",
        "fact_kind",
        "temporal_status",
        "valid_from",
        "episode_id",
    ],
    "Topic": ["name"],
    "Entity": ["name"],
    "Episode": ["episode_id", "channel"],
    "Report": ["report_id", "created_at"],
}


async def ensure_schema(store: GraphStore) -> None:
    for label, properties in NODE_INDEXES.items():
        for prop in properties:
            await _ensure(store, f"CREATE INDEX FOR (n:{label}) ON (n.{prop})")
    await _ensure(
        store,
        "CREATE VECTOR INDEX FOR (f:Fact) ON (f.embedding) OPTIONS "
        f"{{dimension: {settings.EMBEDDING_DIMENSIONS}, similarityFunction: 'cosine'}}",
    )


async def _ensure(store: GraphStore, cypher: str) -> None:
    try:
        await store.query(cypher)
    except Exception as exc:
        if "already indexed" not in str(exc).lower():
            logger.warning(f"Schema statement failed on {store.graph_name}: {exc}")
