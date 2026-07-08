from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from saq.worker import async_check_health as saq_check_health
from tortoise.exceptions import DBConnectionError

from kgmemory.core.logger import logger
from kgmemory.graph.client import get_db
from kgmemory.users.models import User
from kgmemory.worker import queue

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: str = "ok"
    database_online: bool = True
    redis_worker_online: bool = True
    graph_online: bool = True


class ReadinessResponse(BaseModel):
    ready: bool
    database_online: bool
    redis_worker_online: bool
    graph_online: bool


@router.get(
    "/",
    response_model=HealthResponse,
    summary="Liveness probe",
    description="Check if the service is alive and all dependencies are reachable. Returns 503 if any are down.",
    responses={503: {"description": "One or more dependencies unavailable", "model": HealthResponse}},
)
async def check_health(response: Response):
    health = HealthResponse()
    try:
        await User.all().count()
    except DBConnectionError:
        health.database_online = False
        logger.exception("Database connection failed")
    if await saq_check_health(queue) == 1:
        health.redis_worker_online = False
        logger.error("SAQ worker is not online")
    try:
        db = get_db()
        graph = db.select_graph("__readiness__")
        await graph.query("RETURN 1")
    except Exception:
        health.graph_online = False
        logger.exception("FalkorDB connection failed")
    if not all(v for k, v in health.model_dump().items() if k != "status"):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        health.status = "degraded"
    return health


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    description="Check if the service is ready to serve traffic. Returns 503 if not ready.",
    responses={503: {"description": "Not ready", "model": ReadinessResponse}},
)
async def check_readiness(response: Response):
    health = await check_health(response)
    ready = all(v for k, v in health.model_dump().items() if k != "status")
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        ready=ready,
        database_online=health.database_online,
        redis_worker_online=health.redis_worker_online,
        graph_online=health.graph_online,
    )
