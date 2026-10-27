"""Supabase sign-in's second factor (FR-AUTH-05, ZUULA_AUTH_PROVIDER=supabase).

A Public User's Supabase token works straight away. An Expert's is signed out until the API's
own code, tied to that Supabase session, is checked with that session's token; then it works
until sign-out ends it. Tokens are minted with a test HS256 secret, the way Supabase signs them.
"""

import re
import time
import uuid

import jwt
import pytest

from app.adapters import email
from app.core import config

PROJECT = "https://example.supabase.co"
SECRET = "contract-test-jwt-secret-long-enough-for-hs256"


@pytest.fixture(autouse=True)
def _supabase_mode(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", PROJECT)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.setenv("ZUULA_AUTH_PROVIDER", "supabase")
    config.get_supabase_settings.cache_clear()
    yield
    config.get_supabase_settings.cache_clear()


def _token(address: str, session_id: str) -> str:
    claims = {
        "sub": str(uuid.uuid5(uuid.NAMESPACE_URL, address)),
        "aud": "authenticated",
        "iss": f"{PROJECT}/auth/v1",
        "exp": int(time.time()) + 3600,
        "email": address,
        "session_id": session_id,
    }
    return jwt.encode(claims, SECRET, algorithm="HS256")


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _latest_code() -> str:
    message = email.OUTBOX[-1]
    return re.search(r"\b(\d{6})\b", message.get("body") or message.get("message")).group(1)


def test_public_users_need_no_code(core_client):
    token = _token("amina@example.com", "session-public")
    r = core_client.post("/api/v1/auth/supabase/second-factor", headers=_bearer(token))
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "public"
    assert core_client.get("/api/v1/me", headers=_bearer(token)).status_code == 200


def test_experts_need_the_code_sent_for_that_supabase_session(core_client):
    token = _token("david@example.com", "session-expert")
    assert core_client.get("/api/v1/me", headers=_bearer(token)).status_code == 401

    r = core_client.post("/api/v1/auth/supabase/second-factor", headers=_bearer(token))
    assert r.status_code == 200
    challenge = r.json()["challengeId"]
    code = _latest_code()

    # Asking again reuses the live challenge instead of sending another code.
    sent = len(email.OUTBOX)
    again = core_client.post("/api/v1/auth/supabase/second-factor", headers=_bearer(token))
    assert again.json()["challengeId"] == challenge
    assert len(email.OUTBOX) == sent

    # The code is no good with another Supabase session's token, or with none.
    other = _token("david@example.com", "session-elsewhere")
    body = {"challengeId": challenge, "code": code}
    for headers in (_bearer(other), {}):
        r = core_client.post("/api/v1/auth/two-factor/verify", json=body, headers=headers)
        assert r.status_code == 400

    r = core_client.post("/api/v1/auth/two-factor/verify", json=body, headers=_bearer(token))
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "expert"
    assert "zuula_session" not in r.cookies  # Supabase holds this session, not a cookie

    assert core_client.get("/api/v1/me", headers=_bearer(token)).status_code == 200
    assert core_client.get("/api/v1/me", headers=_bearer(other)).status_code == 401

    # Sign-out ends the second-factor record, even though the Supabase token is still valid.
    assert core_client.post("/api/v1/auth/sign-out", headers=_bearer(token)).status_code == 204
    assert core_client.get("/api/v1/me", headers=_bearer(token)).status_code == 401


def test_the_endpoint_is_off_unless_supabase_is_the_provider(core_client, monkeypatch):
    monkeypatch.setenv("ZUULA_AUTH_PROVIDER", "legacy")
    config.get_supabase_settings.cache_clear()
    token = _token("amina@example.com", "session-public")
    r = core_client.post("/api/v1/auth/supabase/second-factor", headers=_bearer(token))
    assert r.status_code == 401
