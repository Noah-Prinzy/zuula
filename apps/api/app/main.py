from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.readiness import assert_production_ready
from app.api.v1 import router as api_v1_router
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.db.session import get_db
from app.partner.v1 import router as partner_v1_router
from app.realtime import redis_client
from app.webhooks import router as webhooks_router
from app.worker import dispatch

settings = get_settings()
# In production, missing adapter credentials stop startup rather than fall back to stubs.
assert_production_ready()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # With JOB_RUNNER=inline there's no Celery beat: the API runs the periodic jobs itself.
    stop = dispatch.start_periodic_jobs()
    yield
    stop()


app = FastAPI(
    lifespan=lifespan,
    title="Zuula API",
    version="0.1.0",
    description=(
        "The core web-app API (/api/v1) and the partner API (/v1). apps/api/openapi.yaml is "
        "the contract; this generated schema isn't."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)

app.include_router(api_v1_router)
app.include_router(partner_v1_router)
app.include_router(webhooks_router)


@app.get("/healthz", tags=["health"])
def healthz():
    """Liveness — the process is up."""
    return {"status": "ok"}


@app.get("/readyz", tags=["health"])
async def readyz(db: AsyncSession = Depends(get_db)):  # noqa: B008
    """Readiness — PostgreSQL and Redis both answer. 503 (with which one failed) otherwise,
    so a load balancer stops routing here until they're back."""
    checks = {"app": "ok"}
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001 — any failure means "not ready"
        checks["database"] = "unavailable"
    try:
        await redis_client.get_async_redis().ping()
        checks["redis"] = "ok"
    except Exception:  # noqa: BLE001
        checks["redis"] = "unavailable"
    ready = all(v == "ok" for v in checks.values())
    return JSONResponse(
        {"status": "ok" if ready else "unavailable", "checks": checks},
        status_code=200 if ready else 503,
    )
