"""Fixtures for the contract suite: the openapi-core-validated app, bound to a real database.

Every `core_client`/`partner_client` test runs the whole app against one PostgreSQL
connection inside a transaction that is rolled back when the test ends, so tests can sign
in, rate, suspend users, revoke keys… without affecting each other or reseeding.

How that works with a sync TestClient: inside `with TestClient(...)` every request runs on
the client's one event loop (its anyio portal), so the connection is opened on that same
loop (`client.portal.call`) and `app.db.session.get_db` is overridden to hand out sessions
bound to it (`join_transaction_mode="create_savepoint"`: a route's commit only releases a
savepoint).

Auth is real (app/core/security.py). Each test starts with a session for each role's sample
user and a partner key, created inside its transaction; the `ADMIN`/`EXPERT`/`JOURNALIST`/
`PUBLIC` header dicts send those sessions as bearer tokens, and `PARTNER_KEY` the key.
"""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from openapi_core import OpenAPI
from openapi_core.configurations import Config
from openapi_core.contrib.fastapi.middlewares import FastAPIOpenAPIMiddleware
from openapi_core.deserializing.media_types.util import data_form_loads, plain_loads
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient
from werkzeug.datastructures import MultiDict

from app.db import models as m
from app.db.seed import SAMPLE_PASSWORD
from app.db.session import get_db
from app.main import app as _app
from app.services.auth import token_hash
from app.services.broadcasts import deliver_channels
from app.services.recompute import recompute_reports
from app.worker import dispatch
from app.worker.messaging import deliver_message
from app.worker.pipeline import run_pipeline

SPEC_PATH = Path(__file__).parent.parent.parent / "openapi.yaml"

# Sample users (app/db/seed.py): Mary (admin), David (expert), Sarah (journalist), Amina
# (public). Tokens are fixed strings — they only exist inside each test's transaction.
ROLE_USERS = {"admin": "u1", "expert": "u2", "journalist": "u4", "public": "u6"}
ROLE_TOKENS = {role: f"test-session-{role}" for role in ROLE_USERS}
ADMIN = {"Authorization": f"Bearer {ROLE_TOKENS['admin']}"}
EXPERT = {"Authorization": f"Bearer {ROLE_TOKENS['expert']}"}
JOURNALIST = {"Authorization": f"Bearer {ROLE_TOKENS['journalist']}"}
PUBLIC = {"Authorization": f"Bearer {ROLE_TOKENS['public']}"}

PARTNER_SECRET = "zl_live_testkey1234567890abcdef"
PARTNER_KEY = {"Authorization": f"Bearer {PARTNER_SECRET}"}

__all__ = ["ADMIN", "EXPERT", "JOURNALIST", "PARTNER_KEY", "PUBLIC", "SAMPLE_PASSWORD"]


def _text_form_loads(value: bytes, **parameters: str):
    return MultiDict(
        [(k, plain_loads(v)) for k, v in data_form_loads(value, **parameters).items(multi=True)]
    )


@pytest.fixture(scope="session")
def validated_app():
    # Wrap _app instead of calling _app.add_middleware(...): that would mutate the shared
    # module-level app singleton in place, which would also affect the plain, unvalidated
    # clients some tests use (the WhatsApp verify tests, the health check).
    #
    # openapi-core ships no default deserializer for text/event-stream (the two SSE
    # endpoints' media type) — it falls back to binary_loads, handing schema validation raw
    # bytes against a `type: string` schema, which always fails. plain_loads (its own
    # text/plain deserializer) is exactly what SSE frames need: decode bytes to str.
    #
    # The same gap for multipart: its data_form_loads keeps every part as bytes, so a
    # `format: binary` file part (SubmissionInput.file) fails `type: string` too. Decoding each
    # part the way plain_loads does lets the file validate as the string OAS 3.0 says it is.
    # This only affects validation; the app still reads the raw upload.
    #
    # Likewise the accreditation document download's binary responses (PDF/image bodies
    # against `type: string, format: binary`).
    binary_types = ("application/pdf", "image/jpeg", "image/png", "image/webp")
    config = Config(
        extra_media_type_deserializers={
            "text/event-stream": plain_loads,
            "multipart/form-data": _text_form_loads,
            **dict.fromkeys((*binary_types, "application/octet-stream"), plain_loads),
        }
    )
    spec = OpenAPI.from_file_path(str(SPEC_PATH), config=config)
    return FastAPIOpenAPIMiddleware(_app, openapi=spec)


async def _seed_credentials(session: AsyncSession) -> None:
    now = datetime.now(UTC)
    for role, user_id in ROLE_USERS.items():
        session.add(
            m.Session(
                id=f"ses-test-{role}",
                user_id=user_id,
                token_hash=token_hash(ROLE_TOKENS[role]),
                device="pytest",
                created_at=now,
                last_active_at=now,
                expires_at=now + timedelta(days=1),
            )
        )
    session.add(
        m.ApiKey(
            id="key-test",
            user_id=ROLE_USERS["journalist"],
            name="Contract tests",
            prefix=PARTNER_SECRET[:12],
            secret_hash=token_hash(PARTNER_SECRET),
            scopes=["submit", "read"],
            created_at=now,
        )
    )
    await session.flush()


@contextmanager
def _bound_client(app, db_url: str, *, base_url: str):
    state: dict = {}

    async def open_transaction():
        state["engine"] = create_async_engine(db_url, poolclass=NullPool)
        state["conn"] = await state["engine"].connect()
        state["txn"] = await state["conn"].begin()
        async with AsyncSession(
            bind=state["conn"], join_transaction_mode="create_savepoint"
        ) as session:
            await _seed_credentials(session)
            await session.commit()

    async def close_transaction():
        await state["txn"].rollback()
        await state["conn"].close()
        await state["engine"].dispose()

    async def override_get_db():
        session = AsyncSession(
            bind=state["conn"], join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            await session.close()

    async def inline_dispatch(tracking_id: str) -> None:
        # In place of the Celery worker: run the pipeline right away, on this test's
        # connection, so the submission is complete when the POST returns.
        async with AsyncSession(
            bind=state["conn"], join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as session:
            await run_pipeline(session, tracking_id)

    async def inline_recompute(report_ids=None) -> None:
        async with AsyncSession(
            bind=state["conn"], join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as session:
            await recompute_reports(session, report_ids)

    async def inline_broadcast(broadcast_id: str) -> None:
        async with AsyncSession(
            bind=state["conn"], join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as session:
            await deliver_channels(session, broadcast_id)

    async def inline_message(channel, to, body, subject=None) -> None:
        await deliver_message(channel, to, body, subject)

    async def run_db(fn):
        async with AsyncSession(
            bind=state["conn"], join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as session:
            result = await fn(session)
            await session.commit()
            return result

    with TestClient(app, base_url=base_url, raise_server_exceptions=True) as client:
        client.portal.call(open_transaction)
        # `client.run_db(async_fn)`: run `await async_fn(session)` inside this test's
        # transaction (on the client's loop), for setup the API itself can't do.
        client.run_db = lambda fn: client.portal.call(run_db, fn)
        _app.dependency_overrides[get_db] = override_get_db
        inline = {
            "dispatch_pipeline": inline_dispatch,
            "dispatch_recompute": inline_recompute,
            "dispatch_broadcast": inline_broadcast,
            "dispatch_message": inline_message,
        }
        real = {name: getattr(dispatch, name) for name in inline}
        for name, fn in inline.items():
            setattr(dispatch, name, fn)
        try:
            yield client
        finally:
            for name, fn in real.items():
                setattr(dispatch, name, fn)
            _app.dependency_overrides.pop(get_db, None)
            client.portal.call(close_transaction)


@pytest.fixture
def core_client(validated_app, migrated_db_url):
    # Matches the `https://zuula.ug` server entry openapi.yaml declares for /api/v1/*.
    # openapi-core enforces the sessionAuth cookie's *presence* on any operation that doesn't
    # override security, independently of the app's own auth — so every request carries a
    # (deliberately invalid) `zuula_session=stub` cookie. The app treats it as "signed out",
    # which is what the no-role tests exercise; role tests add a real bearer session token.
    with _bound_client(validated_app, migrated_db_url, base_url="https://zuula.ug") as client:
        client.cookies.set("zuula_session", "stub")
        yield client


class _PartnerClient:
    """The same client and database transaction as `core_client`, aimed at the partner host
    (`https://api.zuula.ug`, openapi.yaml's server override for /v1/*). One client per test,
    not two: two clients would mean two transactions, and a test that uses both (create a key
    on the core API, call the partner API with it) would never see its own writes — or block
    on its own row locks."""

    BASE = "https://api.zuula.ug"
    # A default, invalid bearer token satisfies openapi-core's presence check for the
    # partnerApiKey scheme, so requests reach require_partner_key, which rejects it with 401
    # — the same outcome as no key at all (TestPartnerApi.test_no_key_rejected).
    DEFAULT_HEADERS = {"Authorization": "Bearer stub_unauthenticated"}

    def __init__(self, client: TestClient):
        self._client = client
        self.run_db = client.run_db

    def request(self, method: str, path: str, *, headers: dict | None = None, **kwargs):
        merged = {**self.DEFAULT_HEADERS, **(headers or {})}
        return self._client.request(method, f"{self.BASE}{path}", headers=merged, **kwargs)

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path, **kwargs):
        return self.request("POST", path, **kwargs)


@pytest.fixture
def partner_client(core_client):
    return _PartnerClient(core_client)
