"""Authentication and role enforcement (ADR 0002 §5). Replaces P2's stub: the X-Zuula-Role
header and "any zl_live_* token works" are gone.

The dependency names and call shapes routers use are unchanged — `Depends(get_current_user)`,
`Depends(require_roles(...))`, `Depends(require_partner_key)` — so no router had to change to
become authenticated for real.

Core API: an opaque session token, from the `zuula_session` cookie or `Authorization: Bearer`
(a bearer value starting `zl_live_` is a partner key, never a session). With
ZUULA_AUTH_PROVIDER=supabase, a bearer JWT is a Supabase access token instead, resolved by
app/core/supabase_auth.py; with it unset, JWTs count as signed out. The token's SHA-256
is looked up in `sessions`; revoked, expired, or belonging to a suspended/deleted user means
signed out. Roles come from the database row, never from the request.

Partner API: `Authorization: Bearer zl_live_…`, looked up by SHA-256 in `api_keys`. The key
must be unrevoked, its owner active and still a journalist or admin (FR-API-02), and it must
carry the scope the method needs (POST = `submit`, GET = `read`, as /developers documents).
Rate limiting is a Redis sliding window per key (FR-API-01), limit from platform settings.
"""

import asyncio
import secrets
import time
from datetime import UTC, datetime, timedelta

from fastapi import Depends, Request
from fastapi.security import HTTPBearer
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rules, supabase_auth
from app.core.config import get_settings, get_supabase_settings
from app.core.errors import ApiError
from app.db.models import ApiKey, ApiUsageHourly, Session, User
from app.db.session import get_db
from app.realtime import redis_client
from app.schemas.account import UserProfile
from app.services.auth import to_profile, token_hash
from app.services.platform_settings import get_platform_settings

ROLE_HIERARCHY = ["public", "journalist", "expert", "admin"]
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# Don't write last-active timestamps on every request.
_TOUCH_INTERVAL = timedelta(minutes=5)


def _session_token(request: Request) -> tuple[str | None, str | None]:
    """(token, source) — source is "bearer" or "cookie"."""
    auth = request.headers.get("authorization", "")
    if auth[:7].lower() == "bearer ":
        token = auth[7:].strip()
        if token and not token.startswith("zl_live_"):
            return token, "bearer"
    token = request.cookies.get(get_settings().session_cookie_name)
    return (token, "cookie") if token else (None, None)


def _check_origin(request: Request) -> None:
    """CSRF defence for cookie-authenticated writes, on top of SameSite=Lax: a browser always
    sends Origin on a cross-site POST/PATCH/DELETE, so one that isn't ours is refused. A
    request with no Origin at all isn't from a browser page and carries no ambient cookie
    risk. Refused as 401 — the cookie simply doesn't count as authentication for a
    cross-site request — which every authenticated operation in the contract declares."""
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in get_settings().cors_origin_list:
        raise ApiError("unauthorized", "Cross-site request refused.")


def _is_jwt(token: str) -> bool:
    # Supabase access tokens are JWTs (header.payload.signature); our session tokens are
    # token_urlsafe() strings, which never contain a dot.
    return token.count(".") == 2


async def _resolve_supabase(db: AsyncSession, token: str) -> tuple[User, None] | None:
    """A Supabase access token's account, or None (signed out) if the token is invalid or the
    account can't sign in, the same as an unknown session token."""
    try:
        # Off the event loop: a JWKS cache miss is a blocking HTTP fetch.
        claims = await asyncio.to_thread(supabase_auth.verify_access_token, token)
        return await supabase_auth.resolve_supabase_user(db, claims), None
    except ApiError:
        return None


async def _resolve_session(
    request: Request, db: AsyncSession
) -> tuple[User, Session | None] | None:
    """(user, session) for the request's credentials. With ZUULA_AUTH_PROVIDER=supabase a
    bearer JWT is a Supabase access token: there is no session row, so session is None.
    Legacy session cookies and bearer tokens keep working alongside."""
    if hasattr(request.state, "auth"):
        return request.state.auth

    token, source = _session_token(request)
    found = None
    if token and source == "bearer" and _is_jwt(token):
        if get_supabase_settings().is_supabase_enabled:
            found = await _resolve_supabase(db, token)
    elif token:
        now = datetime.now(UTC)
        row = (
            await db.execute(
                select(Session, User)
                .join(User, User.id == Session.user_id)
                .where(
                    Session.token_hash == token_hash(token),
                    Session.revoked_at.is_(None),
                    Session.expires_at > now,
                    # "pending" accounts (e.g. awaiting accreditation) still sign in.
                    User.status != "suspended",
                    User.deleted_at.is_(None),
                )
            )
        ).first()
        if row is not None:
            session, user = row
            if source == "cookie" and request.method not in _SAFE_METHODS:
                _check_origin(request)
            if now - session.last_active_at > _TOUCH_INTERVAL:
                session.last_active_at = now
                user.last_active_at = now
                await db.commit()
            found = (user, session)

    request.state.auth = found
    return found


def current_session_id(request: Request) -> str | None:
    """The signed-in session's id (for "this device" on /me/sessions, sign-out). Only valid
    after get_current_user/require_roles ran for this request."""
    auth = getattr(request.state, "auth", None)
    return auth[1].id if auth and auth[1] is not None else None


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> UserProfile | None:
    """The signed-in user, or None when signed out (optional-auth routes)."""
    found = await _resolve_session(request, db)
    return to_profile(found[0]) if found else None


def require_roles(*allowed: str):
    """Dependency factory: 401 unless signed in, 403 unless the user's role (from the database)
    is one of `allowed`. Empty `allowed` means "signed in, any role"."""

    async def _dep(
        request: Request,
        db: AsyncSession = Depends(get_db),  # noqa: B008
    ) -> UserProfile:
        user = await get_current_user(request, db)
        if user is None:
            raise ApiError("unauthorized", "Sign in required.")
        if allowed and user.role not in allowed:
            raise ApiError("forbidden", f"Requires role: {', '.join(allowed)}.")
        return user

    return _dep


# ---- Partner API keys (FR-API-01/02) ----

partner_bearer = HTTPBearer(auto_error=False)
_WINDOW_SECONDS = 3600


class PartnerPrincipal:
    def __init__(self, key: ApiKey, rate_limit_headers: dict[str, str]):
        self.key_id = key.id
        self.key_prefix = key.prefix
        self.user_id = key.user_id
        self.scopes = list(key.scopes)
        # X-RateLimit-* for this request, set on every partner response (FR-API-01).
        self.rate_limit_headers = rate_limit_headers


async def _rate_limit(key_id: str, limit: int) -> dict[str, str]:
    """Sliding one-hour window in a Redis sorted set (one member per request). Adding the
    request and counting happen in one MULTI, so concurrent requests can't both slip in under
    the limit; a request over the limit is removed again and refused."""
    r = redis_client.get_async_redis()
    key = f"zuula:partner-rl:{key_id}"
    now = time.time()
    member = f"{now:.6f}-{secrets.token_hex(4)}"
    async with r.pipeline(transaction=True) as pipe:
        pipe.zremrangebyscore(key, 0, now - _WINDOW_SECONDS)
        pipe.zadd(key, {member: now})
        pipe.zcard(key)
        pipe.zrange(key, 0, 0, withscores=True)
        pipe.expire(key, _WINDOW_SECONDS)
        _, _, count, oldest, _ = await pipe.execute()

    oldest_at = oldest[0][1] if oldest else now
    reset_at = int(oldest_at + _WINDOW_SECONDS)
    headers = {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(max(0, limit - count)),
        "X-RateLimit-Reset": str(reset_at),
    }
    if count > limit:
        await r.zrem(key, member)
        headers["X-RateLimit-Remaining"] = "0"
        raise ApiError(
            "rate_limited",
            f"This key has used its {limit} requests for this hour.",
            retry_after=max(1, reset_at - int(now)),
            headers=headers,
        )
    return headers


async def _record_usage(db: AsyncSession, key: ApiKey) -> None:
    now = datetime.now(UTC)
    hour = now.replace(minute=0, second=0, microsecond=0)
    await db.execute(
        insert(ApiUsageHourly)
        .values(api_key_id=key.id, hour=hour, count=1)
        .on_conflict_do_update(
            index_elements=[ApiUsageHourly.api_key_id, ApiUsageHourly.hour],
            set_={"count": ApiUsageHourly.count + 1},
        )
    )
    if key.last_used_at is None or now - key.last_used_at > timedelta(minutes=1):
        key.last_used_at = now
    await db.commit()


async def require_partner_key(
    request: Request,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> PartnerPrincipal:
    # `credentials` must come from partner_bearer(request), not a plain function parameter:
    # an untyped-as-Depends parameter shaped like a Pydantic model (HTTPAuthorizationCredentials
    # extends BaseModel) is treated by FastAPI as an *implicit request body field*, which then
    # merges with a route's own Body(...) param into a wrapped {"credentials": ..., "body": ...}
    # shape instead of the flat JSON payload callers actually send.
    credentials = await partner_bearer(request)
    secret = credentials.credentials if credentials else ""
    if not secret.startswith("zl_live_"):
        raise ApiError(
            "unauthorized", "Provide a partner API key: Authorization: Bearer zl_live_..."
        )

    row = (
        await db.execute(
            select(ApiKey, User)
            .join(User, User.id == ApiKey.user_id)
            .where(ApiKey.secret_hash == token_hash(secret), ApiKey.revoked_at.is_(None))
        )
    ).first()
    if (
        row is None
        or row.User.status == "suspended"
        or row.User.deleted_at is not None
        or row.User.role not in rules.API_KEY_ROLES
    ):
        raise ApiError("unauthorized", "This API key is invalid or has been revoked.")
    key = row.ApiKey

    needed = "submit" if request.method == "POST" else "read"
    if needed not in key.scopes:
        raise ApiError("forbidden", f"This key doesn't have the '{needed}' scope.")

    limit = (await get_platform_settings(db)).api_rate_limit
    headers = await _rate_limit(key.id, limit)
    await _record_usage(db, key)
    return PartnerPrincipal(key, headers)
