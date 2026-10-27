"""Supabase Auth access tokens: verify them and find the Zuula account they belong to.

Nothing calls this yet. app/core/security.py still signs people in with the legacy
`zuula_session` cookie; Phase 1.2 makes `_resolve_session` fall back to `bearer_token` →
`verify_access_token` → `resolve_supabase_user` when ZUULA_AUTH_PROVIDER=supabase.

Why the linking rules are strict:
- A token is matched to an account by its email, else its phone. That is only safe while the
  Supabase project requires confirmation (Auth → "Confirm email", "Secure email change", and
  phone OTP): then a session only exists for an address its owner proved. `user_metadata` is
  never used for this, since the user can write to it.
- Roles always come from the users table; a token never grants one.
- Anonymous Supabase users are refused.

TODO(Phase 1.2): store the token's `sub` on the account (needs a migration) and look accounts up
by it, so changing an email on the Supabase side doesn't detach the Zuula account.
"""

from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_supabase_settings
from app.core.errors import ApiError
from app.db.base import new_id
from app.db.models import User

_AUDIENCE = "authenticated"
# Supabase signs with the project's asymmetric signing key (published as JWKS), or with the
# legacy shared JWT secret (HS256) on projects that haven't rotated to signing keys.
_ASYMMETRIC_ALGORITHMS = {"ES256", "RS256", "EdDSA"}
_TOUCH_INTERVAL = timedelta(minutes=5)
_INVALID = "Your session is invalid or has expired. Sign in again."


@lru_cache
def _jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    # Caches the signing keys; a token naming an unknown key id triggers one refetch.
    return jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=600)


def bearer_token(request: Request) -> str | None:
    """The `Authorization: Bearer …` token, if any. Only the header: query strings end up in
    access logs, and Supabase JS keeps its session in localStorage, not cookies."""
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


def verify_access_token(token: str) -> dict:
    """The token's claims, or ApiError(unauthorized) if it is forged, expired, or not an
    access token from this project."""
    settings = get_supabase_settings()
    if not settings.supabase_url:
        raise ApiError("unauthorized", "Sign in required.")
    try:
        algorithm = jwt.get_unverified_header(token).get("alg")
        if algorithm in _ASYMMETRIC_ALGORITHMS:
            key = _jwks_client(settings.jwks_url).get_signing_key_from_jwt(token).key
        elif algorithm == "HS256" and settings.supabase_jwt_secret:
            key = settings.supabase_jwt_secret
        else:
            raise ApiError("unauthorized", _INVALID)
        return jwt.decode(
            token,
            key,
            algorithms=[algorithm],
            audience=_AUDIENCE,
            issuer=settings.issuer,
            options={"require": ["exp", "sub", "iss", "aud"]},
        )
    except jwt.PyJWTError as e:
        raise ApiError("unauthorized", _INVALID) from e


def _identifier(claims: dict) -> tuple[str | None, str | None]:
    email = (claims.get("email") or "").strip().lower() or None
    phone = (claims.get("phone") or "").strip() or None
    # Supabase stores phones without the "+"; users.phone is E.164.
    if phone and not phone.startswith("+"):
        phone = f"+{phone}"
    return email, phone


async def resolve_supabase_user(db: AsyncSession, claims: dict) -> User:
    """The account for verified `claims`, created as a `public` account on first sign-in."""
    if claims.get("is_anonymous"):
        raise ApiError("unauthorized", "Sign in with an email address or phone number.")
    email, phone = _identifier(claims)
    if email is None and phone is None:
        raise ApiError("unauthorized", "Sign in required.")
    # Look up and create by one identifier only: the other may belong to a different account.
    column, value = (User.email, email) if email else (User.phone, phone)

    user = (await db.execute(select(User).where(column == value))).scalar_one_or_none()
    now = datetime.now(UTC)
    if user is None:
        metadata = claims.get("user_metadata") or {}
        name = metadata.get("full_name") or metadata.get("name") or (email or "").split("@")[0]
        user = User(
            id=new_id("usr"),
            name=str(name or "Zuula user"),
            email=email,
            phone=None if email else phone,
            email_verified_at=now if email else None,
            phone_verified_at=None if email else now,
            last_active_at=now,
        )
        db.add(user)
        try:
            await db.commit()
        except IntegrityError:
            # Another request created it first (two tabs on first sign-in).
            await db.rollback()
            user = (await db.execute(select(User).where(column == value))).scalar_one()

    # Same rule as the legacy session lookup: "pending" accounts still sign in.
    if user.deleted_at is not None or user.status == "suspended":
        raise ApiError("unauthorized", "Sign in required.")
    if user.last_active_at is None or now - user.last_active_at > _TOUCH_INTERVAL:
        user.last_active_at = now
        await db.commit()
    return user
