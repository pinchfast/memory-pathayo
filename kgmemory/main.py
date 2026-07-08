from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from .actions.routes import router as actions_router
from .contextengine.routes import router as context_router
from .core.auth import get_auth_router
from .core.config import settings
from .core.logger import logger
from .core.metrics import MetricsMiddleware, router as metrics_router
from .core.openapi import custom_openapi
from .db.config import register_db
from .health import router as health_router
from .lifetime import shutdown, startup
from .memory.routes import router as memory_router
from .monitor.routes import router as monitor_router
from .onboarding.routes import router as onboarding_router
from .orgs.routes import router as orgs_router
from .people.routes import router as people_router
from .projects.routes import router as projects_router
from .reports.routes import router as reports_router
from .state.routes import router as state_router
from .users.routes import router as users_router

DESCRIPTION = """\
# PinchFast Memory

The **brain** of an AI project manager that bridges founders and their engineering teams.

## How it works

1. **Ingest** conversations (`POST /memory/ingest`) — founder chats, Slack messages
   relayed from your Django backend. The LLM extracts atomic facts (commitments,
   blockers, skills, status updates, decisions) and stores them in a per-org
   knowledge graph with vector embeddings.

2. **State inference** runs automatically after each ingest — the system derives
   project health and person credibility from the facts and stores durable
   snapshots. This is the PM's continuous model of reality.

3. **Search** (`POST /context/search`) runs hybrid retrieval (vector + graph
   traversal + LLM rerank) and returns a prompt-context string plus current
   project/person states. Your Django backend calls this to give the PM agent
   its memory.

4. **Decide** (`POST /pm/decide`) is the reasoning layer — it synthesizes
   retrieved memory + current states into an audience-tuned response with
   concrete suggested actions (ping, escalate, reassign). Actions are
   auto-queued for the Django backend to execute via `GET /actions`.

5. **Monitor** (`POST /monitor/scan`, `GET /monitor/alerts`) is the autonomous
   risk scanner — runs every 15 minutes via the SAQ worker, detecting overdue
   commitments, engineer silence, single points of failure, and stale blockers.
   Alerts are stored as graph nodes for the backend to act on.

6. **Check-in** (`POST /pm/check-in`, `POST /pm/check-in/auto`) is the proactive
   outreach layer — the PM doesn't wait to be asked, it generates check-in
   messages for silent or at-risk engineers referencing their actual commitments.

7. **Report** (`POST /reports/`) generates LLM-composed founder reports in the
   org's preferred language.

## Authentication

- **Org API keys** (`X-API-Key` header): required for all memory, context, people,
  projects, reports, and PM-brain endpoints. Create one via `POST /orgs/{org_id}/api-keys`
  (requires JWT auth first).
- **JWT** (Bearer token): used for org management and user account endpoints via
  `/auth/login`.

## Multi-tenancy

Each organization gets its own isolated FalkorDB graph (`org_<uuid_hex>`).
Facts, people, and projects are hard-isolated per tenant.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup()
    try:
        yield
    finally:
        await shutdown()


def get_application() -> FastAPI:
    _app = FastAPI(
        title="PinchFast Memory",
        description=DESCRIPTION,
        version="0.1.0",
        debug=settings.DEBUG,
        lifespan=lifespan,
        servers=[
            {"url": str(settings.SERVER_HOST), "description": "Current server"},
        ],
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    _app.add_middleware(MetricsMiddleware)
    _app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS]
        or ["http://localhost"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @_app.exception_handler(500)
    async def internal_error_handler(request: Request, exc: Exception):
        logger.exception(f"Unhandled error on {request.method} {request.url.path}")
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "type": "internal_error"},
        )

    @_app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse(url="/docs")

    @_app.get("/api-info", tags=["system"], summary="API summary", include_in_schema=False)
    async def api_info():
        routes = []
        for route in _app.routes:
            if hasattr(route, "methods") and getattr(route, "path", "") not in (
                "/openapi.json", "/docs", "/redoc", "/",
            ):
                routes.append({
                    "path": route.path,
                    "methods": sorted(route.methods - {"HEAD"}),
                })
        return {
            "name": _app.title,
            "version": _app.version,
            "docs": "/docs",
            "redoc": "/redoc",
            "openapi": "/openapi.json",
            "metrics": "/metrics",
            "endpoints": routes,
        }

    _app.include_router(get_auth_router(), prefix="/v1")
    _app.include_router(users_router, prefix="/v1")
    _app.include_router(orgs_router, prefix="/v1")
    _app.include_router(memory_router, prefix="/v1")
    _app.include_router(monitor_router, prefix="/v1")
    _app.include_router(actions_router, prefix="/v1")
    _app.include_router(context_router, prefix="/v1")
    _app.include_router(onboarding_router, prefix="/v1")
    _app.include_router(people_router, prefix="/v1")
    _app.include_router(projects_router, prefix="/v1")
    _app.include_router(reports_router, prefix="/v1")
    _app.include_router(state_router, prefix="/v1")
    _app.include_router(health_router, prefix="/v1")
    _app.include_router(metrics_router)
    register_db(_app)

    _app.openapi = lambda: custom_openapi(_app)
    return _app


app = get_application()
