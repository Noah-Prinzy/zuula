"""Session-wide test setup, shared by every suite:

- A fake Redis (sync + async, same underlying FakeServer so both sides see the same data)
  in place of a live server — everything goes through app.realtime.redis_client's
  get_redis()/get_async_redis(), so patching those two functions covers every call site.
  Flushed after each test, so rate-limit and sign-in-lockout counters don't leak between
  tests.
- Celery running tasks synchronously ("eager") instead of needing a live worker — every POST
  /api/v1/submissions call in tests/contract/ enqueues a real pipeline task, and the tests
  expect its result to be visible immediately after the request returns.
- A real PostgreSQL (+ pgvector) database (tests/dbutil.py): dropped, recreated, migrated
  with `alembic upgrade head` and seeded once per run (`migrated_db_url`). Tests that need it
  get a `db` session inside a transaction that's rolled back afterwards; tests/contract/ binds
  the whole app to such a transaction (tests/contract/conftest.py).
"""

import asyncio
import os
import weakref

import fakeredis
import pytest
from alembic import command
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.adapters import email, sms
from app.adapters.storage import StubObjectStorage
from app.core.config import (
    get_adapters_settings,
    get_analysis_settings,
    get_language_settings,
    get_settings,
)
from app.realtime import redis_client
from app.worker import celery_app
from tests.dbutil import TEST_DATABASE_URL, alembic_config, recreate_database, seed_database

_fake_server = fakeredis.FakeServer()


@pytest.fixture(autouse=True, scope="session")
def _no_real_language_provider():
    """This environment may carry a real SUNBIRD_API_KEY, which would switch the pipeline to
    Sunbird's live API. The suite never calls a real service: drop it for the whole run
    (tests that exercise Sunbird mock HTTP with respx and configure their own key)."""
    saved = os.environ.pop("SUNBIRD_API_KEY", None)
    get_language_settings.cache_clear()
    yield
    if saved is not None:
        os.environ["SUNBIRD_API_KEY"] = saved
    get_language_settings.cache_clear()


@pytest.fixture(autouse=True, scope="session")
def _no_real_analysis_provider():
    """Same reasoning as `_no_real_language_provider`, for the P4 verdict engine: this
    environment may carry real GROQ_API_KEY/TAVILY_API_KEY, which would switch
    get_analysis_provider()/get_transcription_provider() to Groq/Tavily's live APIs. Tests
    that exercise GroqAnalysisProvider mock HTTP with respx and configure their own keys."""
    saved = {
        name: os.environ.pop(name, None) for name in ("GROQ_API_KEY", "TAVILY_API_KEY")
    }
    get_analysis_settings.cache_clear()
    yield
    for name, value in saved.items():
        if value is not None:
            os.environ[name] = value
    get_analysis_settings.cache_clear()


@pytest.fixture(autouse=True, scope="session")
def _fake_redis_and_eager_celery():
    fake_sync = fakeredis.FakeRedis(server=_fake_server, decode_responses=True)
    # One async client per event loop, all on the same FakeServer: an asyncio Redis client's
    # connections belong to the loop that first used them, and tests run on several loops
    # (pytest-asyncio's, and each contract TestClient's own). Sharing one client across them
    # hangs the second loop. Production has a single loop, so the real client is one per
    # process (app/realtime/redis_client.py).
    async_clients: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()

    def fake_async():
        loop = asyncio.get_running_loop()
        if loop not in async_clients:
            async_clients[loop] = fakeredis.FakeAsyncRedis(
                server=_fake_server, decode_responses=True
            )
        return async_clients[loop]

    redis_client.get_redis.cache_clear()
    redis_client.get_async_redis.cache_clear()
    redis_client.get_redis = lambda: fake_sync
    redis_client.get_async_redis = fake_async

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True

    # Real per-step sleeps (up to ~3s each) would make the suite take minutes; 0 still
    # exercises every branch of app/worker/pipeline.py without the wait.
    get_analysis_settings.cache_clear()
    get_analysis_settings().pipeline_step_scale = 0.0
    # The notification stream replays and closes instead of staying open for live events,
    # so a test's GET of it returns.
    get_settings().notification_stream_seconds = 0

    yield


@pytest.fixture(autouse=True)
def _isolate_per_test_state():
    yield
    fakeredis.FakeRedis(server=_fake_server).flushall()
    sms.OUTBOX.clear()
    email.OUTBOX.clear()
    StubObjectStorage.OBJECTS.clear()


@pytest.fixture
def adapter_env(monkeypatch):
    """`adapter_env(TURNSTILE_SECRET_KEY="x", ...)`: configure adapters for one test. Nothing
    calls a real service: adapter tests mock HTTP with respx, clamd with a local socket and
    S3 with botocore's Stubber."""

    def configure(**variables: str) -> None:
        for name, value in variables.items():
            monkeypatch.setenv(name, value)
        get_adapters_settings.cache_clear()

    yield configure
    get_adapters_settings.cache_clear()


@pytest.fixture(scope="session")
def migrated_db_url() -> str:
    asyncio.run(recreate_database(TEST_DATABASE_URL))
    command.upgrade(alembic_config(TEST_DATABASE_URL), "head")
    asyncio.run(seed_database(TEST_DATABASE_URL))
    return TEST_DATABASE_URL


@pytest.fixture
async def db(migrated_db_url):
    engine = create_async_engine(migrated_db_url, poolclass=NullPool)
    async with engine.connect() as conn:
        outer = await conn.begin()
        # create_savepoint: a test's own session.commit() only releases a savepoint, so the
        # rollback below still undoes everything the test wrote.
        session = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            await session.close()
            await outer.rollback()
    await engine.dispose()
