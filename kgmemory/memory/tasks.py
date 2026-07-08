import json

from kgmemory.core.logger import logger
from kgmemory.core.redis import get_redis

from .ingest import ingest_batch, ingest_message
from .schemas import IngestRequest

STATUS_TTL_SECONDS = 3600


def status_key(request_id: str) -> str:
    return f"ingest:status:{request_id}"


async def set_status(request_id: str, status: str, *, result: dict | None = None, error: str | None = None) -> None:
    payload = {"request_id": request_id, "status": status, "result": result, "error": error}
    await get_redis().set(status_key(request_id), json.dumps(payload), ex=STATUS_TTL_SECONDS)


async def get_status(request_id: str) -> dict | None:
    raw = await get_redis().get(status_key(request_id))
    return json.loads(raw) if raw else None


async def ingest_conversation(_: dict, *, request_id: str, graph_name: str, payload: dict) -> dict:
    await set_status(request_id, "running")
    try:
        result = await ingest_message(graph_name, IngestRequest(**payload))
    except Exception as exc:
        logger.exception(f"Ingest {request_id} failed")
        await set_status(request_id, "failed", error=str(exc))
        raise
    await set_status(request_id, "complete", result=result)
    return result


async def ingest_batch_conversation(
    _: dict, *, request_id: str, graph_name: str, messages: list[dict]
) -> dict:
    await set_status(request_id, "running")
    try:
        result = await ingest_batch(graph_name, [IngestRequest(**m) for m in messages])
    except Exception as exc:
        logger.exception(f"Batch ingest {request_id} failed")
        await set_status(request_id, "failed", error=str(exc))
        raise
    await set_status(request_id, "complete", result=result)
    return result
