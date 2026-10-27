"""Sign-up, sign-in, two-factor, password reset and OAuth (FR-AUTH-01…07). ADR 0002 §5.

Every flow ends in app.services.auth.start_session(): an opaque token set as the
`zuula_session` cookie (HttpOnly, Secure, SameSite=Lax). Codes go out over the identifier's
own channel (SMS for a phone number, email for an address) through app/adapters/.
"""

import asyncio
import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime

from fastapi import Body, Depends, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.oauth import ProviderUnavailable, get_oauth_provider
from app.core import rules, supabase_auth
from app.core.config import get_settings, get_supabase_settings
from app.core.errors import ApiError
from app.core.router import APIRouter
from app.core.security import current_session_id, get_current_user
from app.db.base import new_id
from app.db.models import AuthChallenge, OAuthIdentity, User
from app.db.models import Session as SessionRow
from app.db.session import get_db
from app.schemas.account import Session, TwoFactorChallenge, UserProfile
from app.services import auth as svc

router = APIRouter(prefix="/auth", tags=["auth"])

_SIGNUP_COOKIE = "zuula_signup"
_OAUTH_COOKIE = "zuula_oauth"
_BAD_CREDENTIALS = "That email or phone number and password don't match."
_BAD_CODE = "That code didn't work. Try again, or ask for a new one."
_TOO_MANY = "Too many wrong codes. Wait a few minutes and try again."


def _session_body(user: User) -> dict:
    return Session(user=svc.to_profile(user)).model_dump(
        by_alias=True, mode="json", exclude_none=True
    )


async def _sign_in(
    db: AsyncSession, request: Request, response: Response, user: User, *, remember: bool
) -> dict:
    _, token = await svc.start_session(db, user, request, remember=remember)
    await db.commit()
    svc.set_session_cookie(response, token, remember=remember)
    return _session_body(user)


def _second_factor(user: User) -> svc.Identifier:
    """FR-AUTH-05 codes go by SMS where the account has a phone number, else by email."""
    if user.phone:
        return svc.Identifier("phone", user.phone)
    return svc.Identifier("email", user.email)


# ---- Sign-up (FR-AUTH-01, FR-AUTH-03) ----


@router.post("/sign-up", status_code=202)
async def sign_up(
    response: Response,
    body: dict = Body(...),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    name = (body.get("name") or "").strip()
    ident = svc.parse_identifier(body.get("identifier", ""))
    password = body.get("password") or ""
    if len(name) < 2:
        raise ApiError("invalid_content", "Enter your name.")
    if ident is None:
        raise ApiError("invalid_content", "Enter a valid email address or Ugandan phone number.")
    if body.get("consent") is not True:
        raise ApiError("invalid_content", "Accept the terms and privacy notice to continue.")
    try:
        svc.check_password_policy(password)
    except ApiError as exc:
        raise ApiError("invalid_content", exc.message) from exc
    if await svc.identifier_taken(db, ident):
        raise ApiError("conflict", "An account with that email or phone number already exists.")

    challenge = await svc.create_challenge(
        db,
        purpose="signup",
        ident=ident,
        payload={
            "name": name,
            ident.kind: ident.value,
            "passwordHash": svc.hash_password(password),
            "consentAt": datetime.now(UTC).isoformat(),
        },
    )
    await db.commit()
    # The contract's verify call only carries the code, so this HttpOnly cookie says which
    # sign-up it belongs to (ADR 0002 §5).
    response.set_cookie(
        _SIGNUP_COOKIE,
        challenge.id,
        max_age=rules.OTP_TTL_SECONDS,
        httponly=True,
        secure=get_settings().session_cookie_secure,
        samesite="lax",
        path="/api/v1/auth",
    )
    return {"maskedIdentifier": svc.mask(ident.value)}


@router.post("/sign-up/verify", response_model=None)
async def verify_sign_up(
    request: Request,
    response: Response,
    body: dict = Body(...),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    challenge_id = request.cookies.get(_SIGNUP_COOKIE)
    challenge = await db.get(AuthChallenge, challenge_id) if challenge_id else None
    if not svc.challenge_usable(challenge, "signup"):
        raise ApiError("bad_request", "That code has expired. Start again to get a new one.")
    # Restarting sign-up gives a fresh challenge, so the per-challenge attempt limit alone
    # would allow unlimited guessing at someone else's address; the identifier's lockout
    # counter caps it (contract: this operation only declares 400, so not a 429).
    ip = svc.client_ip(request)
    if await svc.sign_in_retry_after(challenge.destination, ip):
        raise ApiError("bad_request", _TOO_MANY)
    if not svc.check_code(challenge, body.get("code", "")):
        await svc.record_sign_in_failure(challenge.destination, ip)
        await db.commit()
        raise ApiError("bad_request", _BAD_CODE)

    data = challenge.payload
    ident = svc.Identifier("email", data["email"]) if "email" in data else None
    ident = ident or svc.Identifier("phone", data["phone"])
    if await svc.identifier_taken(db, ident):
        await db.commit()
        raise ApiError("bad_request", "That email or phone number was registered meanwhile.")

    now = datetime.now(UTC)
    user = User(
        id=new_id("usr"),
        name=data["name"],
        email=data.get("email"),
        phone=data.get("phone"),
        password_hash=data["passwordHash"],
        role="public",
        status="active",
        email_verified_at=now if "email" in data else None,
        phone_verified_at=now if "phone" in data else None,
        created_at=now,
    )
    db.add(user)
    await db.flush()
    challenge.user_id = user.id
    response.delete_cookie(_SIGNUP_COOKIE, path="/api/v1/auth")
    return await _sign_in(db, request, response, user, remember=True)


# ---- Sign-in and two-factor (FR-AUTH-01, FR-AUTH-05) ----


@router.post("/sign-in", response_model=None)
async def sign_in(
    request: Request,
    response: Response,
    body: dict = Body(...),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    raw = (body.get("identifier") or "").strip()
    password = body.get("password") or ""
    remember = body.get("remember", True) is not False
    if not raw or not password:
        raise ApiError("unauthorized", "Enter your email or phone number and password.")

    ident = svc.parse_identifier(raw)
    lock_key = ident.value if ident else raw.lower()
    ip = svc.client_ip(request)
    retry_after = await svc.sign_in_retry_after(lock_key, ip)
    if retry_after:
        raise ApiError(
            "rate_limited",
            "Too many sign-in attempts. Wait a few minutes and try again.",
            retry_after=retry_after,
        )

    user = await svc.find_user(db, ident) if ident else None
    # verify_password runs bcrypt even when there's no such account, so a wrong identifier
    # and a wrong password take the same time.
    if not svc.verify_password(password, user.password_hash if user else None):
        await svc.record_sign_in_failure(lock_key, ip)
        raise ApiError("unauthorized", _BAD_CREDENTIALS)
    await svc.clear_sign_in_failures(lock_key)
    if user.status == "suspended":
        raise ApiError("unauthorized", "This account is suspended. Contact support@zuula.ug.")

    if svc.needs_two_factor(user):
        second = _second_factor(user)
        challenge = await svc.create_challenge(
            db, purpose="two_factor", ident=second, user=user, payload={"remember": remember}
        )
        await db.commit()
        return TwoFactorChallenge(
            challenge_id=challenge.id, masked_identifier=svc.mask(second.value)
        ).model_dump(by_alias=True)

    return await _sign_in(db, request, response, user, remember=remember)


async def _supabase_claims(request: Request) -> dict:
    """The verified claims of the request's Supabase access token (ZUULA_AUTH_PROVIDER=supabase)."""
    token = supabase_auth.bearer_token(request)
    if not get_supabase_settings().is_supabase_enabled or not token:
        raise ApiError("unauthorized", "Sign in required.")
    # Off the event loop: a JWKS cache miss is a blocking HTTP fetch.
    return await asyncio.to_thread(supabase_auth.verify_access_token, token)


async def _supabase_session_id(request: Request) -> str | None:
    try:
        return (await _supabase_claims(request)).get("session_id")
    except ApiError:
        return None


@router.post("/supabase/second-factor", response_model=None)
async def supabase_second_factor(
    request: Request,
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Supabase sign-in, after the password step (FR-AUTH-05). The account, or for Expert
    Reviewers, Admins and opted-in users a code over the identifier's own channel, tied to this
    Supabase session and checked by /two-factor/verify. Asking again while a code is still
    usable returns the same challenge instead of sending another."""
    claims = await _supabase_claims(request)
    user = await supabase_auth.resolve_supabase_user(db, claims)
    if not svc.needs_two_factor(user) or await supabase_auth.verified_session(db, user, claims):
        return _session_body(user)
    session_id = claims.get("session_id")
    if not session_id:
        raise ApiError("unauthorized", "Sign in again.")

    second = _second_factor(user)
    challenge = (
        (
            await db.execute(
                select(AuthChallenge).where(
                    AuthChallenge.user_id == user.id,
                    AuthChallenge.purpose == "two_factor",
                    AuthChallenge.consumed_at.is_(None),
                    AuthChallenge.attempts < rules.OTP_MAX_ATTEMPTS,
                    AuthChallenge.expires_at > datetime.now(UTC),
                    AuthChallenge.payload["supabase_session"].astext == session_id,
                )
            )
        )
        .scalars()
        .first()
    )
    if challenge is None:
        challenge = await svc.create_challenge(
            db,
            purpose="two_factor",
            ident=second,
            user=user,
            payload={"supabase_session": session_id},
        )
        await db.commit()
    return TwoFactorChallenge(
        challenge_id=challenge.id, masked_identifier=svc.mask(second.value)
    ).model_dump(by_alias=True)


@router.post("/two-factor/verify", response_model=None)
async def verify_two_factor(
    request: Request,
    response: Response,
    body: dict = Body(...),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    challenge_id = body.get("challengeId") or ""
    challenge = await db.get(AuthChallenge, challenge_id) if challenge_id else None
    if not svc.challenge_usable(challenge, "two_factor"):
        raise ApiError("bad_request", "That code has expired. Sign in again to get a new one.")
    # A Supabase sign-in's code is only good with that same Supabase session's token.
    supabase_session = (challenge.payload or {}).get("supabase_session")
    if supabase_session and await _supabase_session_id(request) != supabase_session:
        raise ApiError("bad_request", "That code has expired. Sign in again to get a new one.")
    if not svc.check_code(challenge, body.get("code", "")):
        await db.commit()
        raise ApiError("bad_request", _BAD_CODE)

    user = await db.get(User, challenge.user_id)
    if user is None or user.status == "suspended" or user.deleted_at is not None:
        await db.commit()
        raise ApiError("bad_request", "This account can't sign in.")
    if supabase_session:
        supabase_auth.start_verified_session(db, user, request, supabase_session)
        await db.commit()
        return _session_body(user)
    remember = (challenge.payload or {}).get("remember", True)
    return await _sign_in(db, request, response, user, remember=remember)


@router.post("/two-factor/resend", status_code=202)
async def resend_two_factor(
    body: dict = Body(...),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    challenge_id = body.get("challengeId") or ""
    challenge = await db.get(AuthChallenge, challenge_id) if challenge_id else None
    # A resend may revive an expired code, but never a used or locked-out one. Unknown ids get
    # the same 202, so the endpoint doesn't reveal which challenges exist.
    if (
        challenge is not None
        and challenge.purpose == "two_factor"
        and challenge.consumed_at is None
        and challenge.attempts < rules.OTP_MAX_ATTEMPTS
    ):
        await svc.resend_challenge(challenge)
        await db.commit()
    return {}


@router.post("/sign-out", status_code=204)
async def sign_out(
    request: Request,
    response: Response,
    user: UserProfile | None = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    session_id = current_session_id(request)
    if session_id:
        row = await db.get(SessionRow, session_id)
        if row is not None and row.revoked_at is None:
            row.revoked_at = datetime.now(UTC)
            await db.commit()
    svc.clear_session_cookie(response)
    response.status_code = 204
    return None


# ---- Password reset ----


@router.post("/forgot-password", status_code=202)
async def forgot_password(
    body: dict = Body(...),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    # Always 202, whether or not an account exists: the response mustn't reveal who has one.
    ident = svc.parse_identifier(body.get("identifier", ""))
    user = await svc.find_user(db, ident) if ident else None
    if user is not None and user.status != "suspended":
        recent = (
            await db.scalars(
                select(AuthChallenge)
                .where(
                    AuthChallenge.user_id == user.id,
                    AuthChallenge.purpose == "password_reset",
                    AuthChallenge.consumed_at.is_(None),
                )
                .order_by(AuthChallenge.last_sent_at.desc())
                .limit(1)
            )
        ).first()
        cooldown = rules.OTP_RESEND_COOLDOWN_SECONDS
        if recent is None or (datetime.now(UTC) - recent.last_sent_at).total_seconds() >= cooldown:
            await svc.create_challenge(db, purpose="password_reset", ident=ident, user=user)
            await db.commit()
    return {}


@router.post("/reset-password")
async def reset_password(
    request: Request,
    body: dict = Body(...),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    password = body.get("password") or ""
    svc.check_password_policy(password)
    ident = svc.parse_identifier(body.get("identifier", ""))
    ip = svc.client_ip(request)
    # Wrong reset codes count toward the identifier's lockout, like wrong passwords: asking
    # for a new code every 30 s mustn't mean unlimited guesses (400: the only error declared).
    if ident and await svc.sign_in_retry_after(ident.value, ip):
        raise ApiError("bad_request", _TOO_MANY)
    user = await svc.find_user(db, ident) if ident else None
    challenge = None
    if user is not None:
        challenge = (
            await db.scalars(
                select(AuthChallenge)
                .where(
                    AuthChallenge.user_id == user.id,
                    AuthChallenge.purpose == "password_reset",
                    AuthChallenge.destination == ident.value,
                )
                .order_by(AuthChallenge.last_sent_at.desc())
                .limit(1)
            )
        ).first()
    if not svc.challenge_usable(challenge, "password_reset"):
        if ident:
            await svc.record_sign_in_failure(ident.value, ip)
        raise ApiError("bad_request", "That code has expired. Ask for a new one.")
    if not svc.check_code(challenge, body.get("code", "")):
        await svc.record_sign_in_failure(ident.value, ip)
        await db.commit()
        raise ApiError("bad_request", _BAD_CODE)

    user.password_hash = svc.hash_password(password)
    await svc.revoke_sessions(db, user.id)  # a reset signs every device out
    await svc.clear_sign_in_failures(ident.value)
    await db.commit()
    return {}


# ---- OAuth (FR-AUTH-01): Google, Facebook ----


def _sign(value: str) -> str:
    key = get_settings().secret_key.encode()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


def _safe_next(next_path: str | None) -> str:
    """Only a path on the web app — never an absolute or protocol-relative URL (no open
    redirect through the callback)."""
    if next_path and next_path.startswith("/") and not next_path.startswith("//"):
        return next_path
    return "/"


def _web(path: str) -> str:
    return f"{get_settings().web_app_url.rstrip('/')}{path}"


def _callback_url(request: Request, provider: str) -> str:
    return str(request.url_for("oauth_callback", provider=provider))


@router.get("/oauth/{provider}/start")
def start_oauth(provider: str, request: Request, next: str | None = None):  # noqa: A002
    if provider not in ("google", "facebook"):
        raise ApiError("not_found", f"Unknown provider '{provider}'.")
    nonce = secrets.token_urlsafe(24)
    next_b64 = base64.urlsafe_b64encode(_safe_next(next).encode()).decode()
    try:
        oauth = get_oauth_provider(provider)
    except ProviderUnavailable:
        # Production without this provider's credentials: back to the sign-in page.
        return RedirectResponse(_web("/sign-in?error=oauth-unavailable"), status_code=302)
    url = oauth.authorize_url(redirect_uri=_callback_url(request, provider), state=nonce)
    redirect = RedirectResponse(url, status_code=302)
    # CSRF for the OAuth round trip: the provider echoes `state` back, and it must match
    # this signed, short-lived cookie.
    value = f"{nonce}.{next_b64}"
    redirect.set_cookie(
        _OAUTH_COOKIE,
        f"{value}.{_sign(value)}",
        max_age=600,
        httponly=True,
        secure=get_settings().session_cookie_secure,
        samesite="lax",
        path="/api/v1/auth/oauth",
    )
    return redirect


@router.get("/oauth/{provider}/callback", name="oauth_callback")
async def oauth_callback(
    provider: str,
    request: Request,
    code: str = "",
    state: str = "",
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    if provider not in ("google", "facebook"):
        raise ApiError("not_found", f"Unknown provider '{provider}'.")

    def fail(reason: str) -> RedirectResponse:
        redirect = RedirectResponse(_web(f"/sign-in?error={reason}"), status_code=302)
        redirect.delete_cookie(_OAUTH_COOKIE, path="/api/v1/auth/oauth")
        return redirect

    cookie = request.cookies.get(_OAUTH_COOKIE, "")
    nonce, _, rest = cookie.partition(".")
    next_b64, _, signature = rest.partition(".")
    if (
        not code
        or not nonce
        or not hmac.compare_digest(signature, _sign(f"{nonce}.{next_b64}"))
        or not hmac.compare_digest(nonce, state)
    ):
        return fail("oauth")
    next_path = _safe_next(base64.urlsafe_b64decode(next_b64.encode()).decode())

    try:
        profile = await get_oauth_provider(provider).exchange_code(
            code=code, redirect_uri=_callback_url(request, provider)
        )
    except Exception:  # noqa: BLE001 — any provider failure is the same "try again" to the user
        return fail("oauth")

    identity = (
        await db.scalars(
            select(OAuthIdentity).where(
                OAuthIdentity.provider == provider, OAuthIdentity.subject == profile.subject
            )
        )
    ).first()
    user = await db.get(User, identity.user_id) if identity else None
    if user is None and profile.email:
        # The provider has verified this address, so it's safe to link it to an existing
        # account with the same email.
        user = await svc.find_user(db, svc.Identifier("email", profile.email.lower()))
    now = datetime.now(UTC)
    if user is None:
        user = User(
            id=new_id("usr"),
            name=profile.name or "Zuula user",
            email=profile.email.lower() if profile.email else None,
            role="public",
            status="active",
            email_verified_at=now,
            created_at=now,
        )
        db.add(user)
        await db.flush()
    if identity is None:
        db.add(
            OAuthIdentity(
                id=new_id("oid"),
                user_id=user.id,
                provider=provider,
                subject=profile.subject,
                email=profile.email,
            )
        )
    if user.status == "suspended" or user.deleted_at is not None:
        await db.commit()
        return fail("suspended")

    if svc.needs_two_factor(user):
        challenge = await svc.create_challenge(
            db,
            purpose="two_factor",
            ident=_second_factor(user),
            user=user,
            payload={"remember": True},
        )
        await db.commit()
        redirect = RedirectResponse(
            _web(f"/sign-in/two-factor?challenge={challenge.id}"), status_code=302
        )
    else:
        _, token = await svc.start_session(db, user, request, remember=True)
        await db.commit()
        redirect = RedirectResponse(_web(next_path), status_code=302)
        svc.set_session_cookie(redirect, token, remember=True)
    redirect.delete_cookie(_OAUTH_COOKIE, path="/api/v1/auth/oauth")
    return redirect
