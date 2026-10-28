import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.email import get_email_sender
from app.adapters.readiness import assert_production_ready
from app.api.v1 import router as api_v1_router
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.db.session import get_db
from app.partner.v1 import router as partner_v1_router
from app.realtime import redis_client
from app.webhooks import router as webhooks_router
from app.worker import dispatch

logger = logging.getLogger("zuula.health")
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


# Brevo's key is checked at most every 10 minutes: readyz may be polled often (UptimeRobot).
EMAIL_CHECK_SECONDS = 600
_email_check: dict = {"at": 0.0, "ok": True}


async def _email_ok() -> bool | None:
    """None when the email sender has no check (SMTP, the stub); else whether Brevo takes
    the key, cached for EMAIL_CHECK_SECONDS."""
    sender = get_email_sender()
    if not hasattr(sender, "check"):
        return None
    if time.monotonic() - _email_check["at"] > EMAIL_CHECK_SECONDS or not _email_check["at"]:
        try:
            await sender.check()
            _email_check["ok"] = True
        except Exception as e:  # noqa: BLE001
            _email_check["ok"] = False
            _log_unavailable("email", e)
        _email_check["at"] = time.monotonic()
    return _email_check["ok"]


def _log_unavailable(what: str, error: Exception) -> None:
    # The error's type and message say why (DNS, TLS, auth); connection URLs aren't in them.
    # WARNING, so it shows under plain uvicorn, which doesn't print the app's INFO logs.
    logger.warning("readyz: %s unavailable: %s: %s", what, type(error).__name__, error)


@app.get("/readyz", tags=["health"])
async def readyz(db: AsyncSession = Depends(get_db)):  # noqa: B008
    """Readiness — PostgreSQL and Redis both answer, and Brevo accepts the email key when
    email goes through Brevo. 503 (with which one failed) otherwise, so monitoring notices
    before sign-in codes stop arriving."""
    checks = {"app": "ok"}
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:  # noqa: BLE001 — any failure means "not ready"
        checks["database"] = "unavailable"
        _log_unavailable("database", e)
    try:
        await redis_client.get_async_redis().ping()
        checks["redis"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["redis"] = "unavailable"
        _log_unavailable("redis", e)
    email = await _email_ok()
    if email is not None:
        checks["email"] = "ok" if email else "unavailable"
    ready = all(v == "ok" for v in checks.values())
    return JSONResponse(
        {"status": "ok" if ready else "unavailable", "checks": checks},
        status_code=200 if ready else 503,
    )
