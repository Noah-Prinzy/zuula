"""app/core/security.py with Supabase Auth: a bearer JWT signs in only when
ZUULA_AUTH_PROVIDER=supabase and the token is valid; legacy session tokens still take the
session-table path; and a Supabase sign-in has no session row.
"""

import time

import jwt
import pytest
from starlette.requests import Request

from app.core import config, security, supabase_auth
from app.db.models import User

PROJECT = "https://example.supabase.co"
SECRET = "test-jwt-secret-that-is-long-enough-for-hs256"


@pytest.fixture
def provider(monkeypatch):
    def _set(name: str):
        monkeypatch.setenv("SUPABASE_URL", PROJECT)
        monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
        monkeypatch.setenv("ZUULA_AUTH_PROVIDER", name)
        config.get_supabase_settings.cache_clear()

    yield _set
    config.get_supabase_settings.cache_clear()


def _token(**overrides):
    claims = {
        "sub": "6f1c0a52-0000-4000-8000-000000000001",
        "aud": "authenticated",
        "iss": f"{PROJECT}/auth/v1",
        "exp": int(time.time()) + 3600,
        "email": "amina@example.com",
    }
    return jwt.encode({**claims, **overrides}, SECRET, algorithm="HS256")


def _request(token: str) -> Request:
    headers = [(b"authorization", f"Bearer {token}".encode())]
    return Request({"type": "http", "method": "GET", "headers": headers})


class _NoSessionsDb:
    """The legacy lookup's `execute(...).first()` finds nothing; counts the lookups."""

    def __init__(self):
        self.lookups = 0

    async def execute(self, statement):
        self.lookups += 1
        return type("Result", (), {"first": lambda self: None})()


async def test_jwts_are_ignored_while_the_provider_is_legacy(provider, monkeypatch):
    provider("legacy")

    async def _fail(*args):
        raise AssertionError("Supabase path must not run in legacy mode")

    monkeypatch.setattr(security, "_resolve_supabase", _fail)
    db = _NoSessionsDb()
    assert await security._resolve_session(_request(_token()), db) is None
    assert db.lookups == 0


async def test_a_valid_supabase_token_signs_in_without_a_session_row(provider, monkeypatch):
    provider("supabase")
    account = User(id="usr_amina", name="Amina", role="journalist", status="active")

    async def _resolve(db, claims):
        assert claims["email"] == "amina@example.com"
        return account

    monkeypatch.setattr(supabase_auth, "resolve_supabase_user", _resolve)
    request = _request(_token())
    assert await security._resolve_session(request, _NoSessionsDb()) == (account, None)
    assert security.current_session_id(request) is None


async def test_an_invalid_supabase_token_is_signed_out(provider):
    provider("supabase")
    expired = _token(exp=int(time.time()) - 10)
    assert await security._resolve_session(_request(expired), _NoSessionsDb()) is None


async def test_legacy_session_tokens_still_use_the_sessions_table(provider):
    provider("supabase")
    db = _NoSessionsDb()
    assert await security._resolve_session(_request("legacy-session-token_abc"), db) is None
    assert db.lookups == 1
