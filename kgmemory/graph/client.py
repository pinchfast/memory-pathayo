from __future__ import annotations

from typing import Any

from falkordb.asyncio import FalkorDB

from kgmemory.core.config import settings
from kgmemory.core.logger import logger

_db: FalkorDB | None = None
_prepared_graphs: set[str] = set()


def get_db() -> FalkorDB:
    global _db
    if _db is None:
        _db = FalkorDB(
            host=settings.FALKORDB_HOST,
            port=settings.FALKORDB_PORT,
            username=settings.FALKORDB_USERNAME,
            password=settings.FALKORDB_PASSWORD,
        )
    return _db


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.connection.aclose()
        _db = None
        _prepared_graphs.clear()


class GraphStore:
    """Cypher access to a single organization's graph."""

    def __init__(self, graph_name: str):
        self.graph_name = graph_name
        self._graph = get_db().select_graph(graph_name)

    async def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
        result = await self._graph.query(cypher, params or {})
        return result.result_set

    async def ping(self) -> bool:
        try:
            await self.query("RETURN 1")
            return True
        except Exception:
            logger.exception("FalkorDB ping failed")
            return False


async def get_org_store(graph_name: str) -> GraphStore:
    from .schema import ensure_schema

    store = GraphStore(graph_name)
    if graph_name not in _prepared_graphs:
        await ensure_schema(store)
        _prepared_graphs.add(graph_name)
    return store
