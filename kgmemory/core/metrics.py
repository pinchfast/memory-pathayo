import time

from fastapi import APIRouter, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware

HTTP_REQUESTS = Counter(
    "kgmemory_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)
HTTP_LATENCY = Histogram(
    "kgmemory_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
)
FACTS_INGESTED = Counter(
    "kgmemory_facts_ingested_total", "Facts written to the graph", ["org"]
)
LLM_CALLS = Counter(
    "kgmemory_llm_calls_total", "LLM calls by outcome", ["kind", "outcome"]
)
SEARCHES = Counter("kgmemory_searches_total", "Context searches", ["org"])

router = APIRouter()


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        HTTP_REQUESTS.labels(request.method, path, response.status_code).inc()
        HTTP_LATENCY.labels(request.method, path).observe(time.perf_counter() - start)
        return response
