from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .contextengine.routes import router as context_router
from .core.auth import get_auth_router
from .core.config import settings
from .core.metrics import MetricsMiddleware, router as metrics_router
from .db.config import register_db
from .health import router as health_router
from .lifetime import shutdown, startup
from .memory.routes import router as memory_router
from .orgs.routes import router as orgs_router
from .people.routes import router as people_router
from .projects.routes import router as projects_router
from .reports.routes import router as reports_router
from .users.routes import router as users_router


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
        description="AI project manager memory and decision microservice",
        version="0.1.0",
        debug=settings.DEBUG,
        lifespan=lifespan,
    )
    _app.add_middleware(MetricsMiddleware)
    _app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS] or ["http://localhost"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    _app.include_router(get_auth_router())
    _app.include_router(users_router)
    _app.include_router(orgs_router)
    _app.include_router(memory_router)
    _app.include_router(context_router)
    _app.include_router(people_router)
    _app.include_router(projects_router)
    _app.include_router(reports_router)
    _app.include_router(health_router)
    _app.include_router(metrics_router)
    register_db(_app)
    return _app


app = get_application()
