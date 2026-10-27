"""app/core/supabase_auth.py's token checks: only an unexpired access token signed for this
Supabase project gets through, by either the legacy HS256 secret or the project's JWKS key.
"""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from starlette.requests import Request

from app.core import config, supabase_auth
from app.core.errors import ApiError
from app.db.models import User

PROJECT = "https://example.supabase.co"
SECRET = "test-jwt-secret-that-is-long-enough-for-hs256"


@pytest.fixture(autouse=True)
def _supabase_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", PROJECT)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    config.get_supabase_settings.cache_clear()
    yield
    config.get_supabase_settings.cache_clear()


def _claims(**overrides):
    claims = {
        "sub": "6f1c0a52-0000-4000-8000-000000000001",
        "aud": "authenticated",
        "iss": f"{PROJECT}/auth/v1",
        "exp": int(time.time()) + 3600,
        "email": "Amina@Example.com",
    }
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


def test_accepts_a_valid_hs256_token():
    token = jwt.encode(_claims(), SECRET, algorithm="HS256")
    assert supabase_auth.verify_access_token(token)["sub"] == _claims()["sub"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": int(time.time()) - 10},
        {"aud": "anon"},
        {"iss": "https://other.supabase.co/auth/v1"},
        {"exp": None},
    ],
    ids=["expired", "wrong-audience", "other-project", "no-expiry"],
)
def test_rejects_tokens_not_issued_for_this_project(overrides):
    token = jwt.encode(_claims(**overrides), SECRET, algorithm="HS256")
    with pytest.raises(ApiError):
        supabase_auth.verify_access_token(token)


def test_rejects_a_token_signed_with_another_secret():
    token = jwt.encode(_claims(), "not-the-project-secret-but-equally-long", algorithm="HS256")
    with pytest.raises(ApiError):
        supabase_auth.verify_access_token(token)


def test_rejects_unsigned_tokens():
    token = jwt.encode(_claims(), None, algorithm="none")
    with pytest.raises(ApiError):
        supabase_auth.verify_access_token(token)


def test_rejects_hs256_when_no_secret_is_configured(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "")
    config.get_supabase_settings.cache_clear()
    token = jwt.encode(_claims(), SECRET, algorithm="HS256")
    with pytest.raises(ApiError):
        supabase_auth.verify_access_token(token)


def test_accepts_es256_tokens_signed_by_the_jwks_key(monkeypatch):
    private_key = ec.generate_private_key(ec.SECP256R1())

    class _Jwks:
        def get_signing_key_from_jwt(self, token):
            return type("SigningKey", (), {"key": private_key.public_key()})()

    monkeypatch.setattr(supabase_auth, "_jwks_client", lambda url: _Jwks())
    token = jwt.encode(_claims(), private_key, algorithm="ES256")
    assert supabase_auth.verify_access_token(token)["email"] == "Amina@Example.com"

    forged = jwt.encode(_claims(), ec.generate_private_key(ec.SECP256R1()), algorithm="ES256")
    with pytest.raises(ApiError):
        supabase_auth.verify_access_token(forged)


def _request(authorization: str | None) -> Request:
    headers = [(b"authorization", authorization.encode())] if authorization else []
    return Request({"type": "http", "headers": headers, "query_string": b"access_token=x"})


def test_bearer_token_reads_only_the_authorization_header():
    assert supabase_auth.bearer_token(_request("Bearer abc.def.ghi")) == "abc.def.ghi"
    assert supabase_auth.bearer_token(_request("Basic dXNlcjpwYXNz")) is None
    assert supabase_auth.bearer_token(_request(None)) is None


def test_identifier_normalises_email_and_phone():
    assert supabase_auth._identifier({"email": " Amina@Example.com "}) == (
        "amina@example.com",
        None,
    )
    assert supabase_auth._identifier({"email": "", "phone": "256700000001"}) == (
        None,
        "+256700000001",
    )


class _FakeDb:
    """Just enough AsyncSession for resolve_supabase_user: `select(User).where(col == value)`
    lookups over an in-memory list, and commits that only count."""

    def __init__(self, *users):
        self.users = list(users)
        self.commits = 0

    async def execute(self, statement):
        clause = statement.whereclause
        column, value = clause.left.key, clause.right.value
        found = [u for u in self.users if getattr(u, column) == value]

        class _Result:
            def scalar_one_or_none(self):
                return found[0] if found else None

            def scalar_one(self):
                return found[0]

        return _Result()

    def add(self, user):
        self.users.append(user)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass


def _user(**fields):
    defaults = {
        "id": "usr_existing",
        "name": "Amina",
        "email": "amina@example.com",
        "phone": None,
        "supabase_user_id": None,
        "status": "active",
        "deleted_at": None,
        "last_active_at": None,
    }
    return User(**{**defaults, **fields})


SUBJECT = _claims()["sub"]


async def test_first_sign_in_links_the_account_with_that_email():
    existing = _user()
    db = _FakeDb(existing)
    user = await supabase_auth.resolve_supabase_user(db, _claims())
    assert user is existing
    assert user.supabase_user_id == SUBJECT


async def test_later_sign_ins_find_the_account_by_subject_even_after_an_email_change():
    linked = _user(supabase_user_id=SUBJECT)
    db = _FakeDb(linked)
    user = await supabase_auth.resolve_supabase_user(db, _claims(email="new@example.com"))
    assert user is linked
    assert user.email == "amina@example.com"


async def test_an_account_linked_to_another_supabase_user_is_not_taken_over():
    db = _FakeDb(_user(supabase_user_id="someone-else"))
    with pytest.raises(ApiError):
        await supabase_auth.resolve_supabase_user(db, _claims())


async def test_new_people_get_a_public_account_with_no_role_from_the_token():
    db = _FakeDb()
    claims = _claims(app_metadata={"role": "admin"}, user_metadata={"role": "admin"})
    user = await supabase_auth.resolve_supabase_user(db, claims)
    assert user.role in (None, "public")  # column default "public" applies on insert
    assert user.supabase_user_id == SUBJECT
    assert user.email == "amina@example.com"
    assert user.id.startswith("usr_")


async def test_suspended_and_anonymous_users_are_refused():
    with pytest.raises(ApiError):
        await supabase_auth.resolve_supabase_user(
            _FakeDb(_user(supabase_user_id=SUBJECT, status="suspended")), _claims()
        )
    with pytest.raises(ApiError):
        await supabase_auth.resolve_supabase_user(_FakeDb(), _claims(is_anonymous=True))
