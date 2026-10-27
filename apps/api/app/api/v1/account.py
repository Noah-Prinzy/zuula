"""The signed-in user's own account (FR-AUTH, §10.1): profile, password, two-factor, devices,
data export and deletion, journalist accreditation, and activity history."""

from datetime import UTC, datetime, timedelta

from fastapi import Body, Depends, File, Form, Request, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.storage import get_object_storage
from app.core import rules
from app.core.errors import ApiError
from app.core.pagination import PageParams, page_params
from app.core.router import APIRouter
from app.core.security import current_session_id, require_roles
from app.db.base import new_id
from app.db.models import (
    AccreditationApplication,
    ApiKey,
    ApiUsageHourly,
    FactCheckReport,
    OAuthIdentity,
    Rating,
    RatingComment,
    Session,
    Submission,
    User,
)
from app.db.models.identity import ACCREDITATION_ROLES
from app.db.session import get_db
from app.schemas.account import AccreditationStatus, DeviceSession, UserProfile
from app.schemas.submission import ActivityRating, ActivitySubmission
from app.services import auth as svc

router = APIRouter(tags=["account"])

_signed_in = require_roles()  # any signed-in role
_DOCUMENT_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}


async def _me(db: AsyncSession, user: UserProfile) -> User:
    row = await db.get(User, user.id)
    if row is None:  # the session resolved it moments ago; only a concurrent delete gets here
        raise ApiError("unauthorized", "Sign in required.")
    return row


def _dump(model) -> dict:
    return model.model_dump(by_alias=True, mode="json", exclude_none=True)


@router.get("/me", response_model=UserProfile)
def get_me(user: UserProfile = Depends(_signed_in)):  # noqa: B008
    return user


@router.patch("/me", response_model=UserProfile)
async def update_me(
    body: dict = Body(...),  # noqa: B008
    user: UserProfile = Depends(_signed_in),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    me = await _me(db, user)
    if "name" in body:
        name = (body["name"] or "").strip()
        if len(name) < 2:
            raise ApiError("invalid_content", "Enter your name.")
        me.name = name
    if "preferredLanguage" in body:
        me.preferred_language = body["preferredLanguage"] or None
    if "district" in body:
        me.district = (body["district"] or "").strip() or None
    for kind in ("email", "phone"):
        if kind not in body:
            continue
        ident = svc.parse_identifier(body[kind] or "")
        if ident is None or ident.kind != kind:
            raise ApiError("invalid_content", f"Enter a valid {kind}.")
        if ident.value == getattr(me, kind):
            continue
        if await svc.identifier_taken(db, ident):
            raise ApiError("invalid_content", f"That {kind} is already used by another account.")
        # A changed identifier is unverified until the user confirms a code sent to it.
        setattr(me, kind, ident.value)
        setattr(me, f"{kind}_verified_at", None)
    await db.commit()
    return svc.to_profile(me)


@router.delete("/me", status_code=202)
async def delete_me(
    user: UserProfile = Depends(_signed_in),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """§10.1 right to erasure. Personal data is removed now; the row stays (anonymised) so the
    audit log, ratings and review history that point at it remain consistent. Ratings keep
    counting — they're anonymous aggregates — but can no longer be traced to the person."""
    me = await _me(db, user)
    now = datetime.now(UTC)
    me.name = "Deleted user"
    me.email = f"deleted-{me.id}@deleted.zuula.invalid"  # the row still needs an identifier
    me.phone = None
    me.password_hash = None
    me.district = None
    me.two_factor_enabled = False
    me.deleted_at = now
    await db.execute(delete(OAuthIdentity).where(OAuthIdentity.user_id == me.id))
    for key in await db.scalars(select(ApiKey).where(ApiKey.user_id == me.id)):
        key.revoked_at = key.revoked_at or now
    await svc.revoke_sessions(db, me.id)
    await db.commit()
    return {}


@router.post("/me/password")
async def change_password(
    request: Request,
    body: dict = Body(...),  # noqa: B008
    user: UserProfile = Depends(_signed_in),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    me = await _me(db, user)
    new_password = body.get("newPassword") or ""
    # An OAuth-only account has no password yet, so there's nothing to confirm.
    if me.password_hash is not None and not svc.verify_password(
        body.get("currentPassword") or "", me.password_hash
    ):
        raise ApiError("unauthorized", "Your current password isn't right.")
    svc.check_password_policy(new_password)
    me.password_hash = svc.hash_password(new_password)
    # Keep this device signed in; sign every other one out.
    await svc.revoke_sessions(db, me.id, except_id=current_session_id(request))
    await db.commit()
    return {}


@router.post("/me/two-factor")
async def set_two_factor(
    body: dict = Body(...),  # noqa: B008
    user: UserProfile = Depends(_signed_in),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    enabled = body.get("enabled")
    if not isinstance(enabled, bool):
        raise ApiError("bad_request", "enabled must be true or false.")
    me = await _me(db, user)
    if not enabled and me.role in rules.TWO_FACTOR_ROLES:
        raise ApiError(
            "bad_request", "Two-factor sign-in is required for Expert Reviewers and Admins."
        )
    me.two_factor_enabled = enabled
    await db.commit()
    return {}


def _ago(then: datetime, now: datetime) -> str:
    """DeviceSession.lastActive is a human phrase ("2 hours ago"), per the contract."""
    seconds = (now - then).total_seconds()
    if seconds < 10 * 60:
        return "Active now"
    for unit, size in (("day", 86_400), ("hour", 3_600), ("minute", 60)):
        n = int(seconds // size)
        if n >= 1:
            return f"{n} {unit}{'s' if n != 1 else ''} ago"
    return "Active now"


@router.get("/me/sessions", response_model=list)
async def list_sessions(
    request: Request,
    user: UserProfile = Depends(_signed_in),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    now = datetime.now(UTC)
    current = current_session_id(request)
    rows = await db.scalars(
        select(Session)
        .where(Session.user_id == user.id, Session.revoked_at.is_(None), Session.expires_at > now)
        .order_by(Session.last_active_at.desc())
    )
    return [
        _dump(
            DeviceSession(
                id=s.id,
                device=s.device,
                location=s.location or "Unknown location",
                last_active=_ago(s.last_active_at, now),
                current=s.id == current,
            )
        )
        for s in rows
    ]


@router.delete("/me/sessions/{id}", status_code=204)
async def revoke_session(
    id: str,  # noqa: A002
    request: Request,
    user: UserProfile = Depends(_signed_in),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    if id == "others":
        await svc.revoke_sessions(db, user.id, except_id=current_session_id(request))
    else:
        row = await db.get(Session, id)
        # Someone else's (or an unknown) session id gets the same 204: nothing to reveal.
        if row is not None and row.user_id == user.id and row.revoked_at is None:
            row.revoked_at = datetime.now(UTC)
    await db.commit()
    return None


@router.get("/me/data-export")
async def export_my_data(
    user: UserProfile = Depends(_signed_in),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """§10.1 data portability: everything we hold that the user created."""
    submissions = await db.scalars(
        select(Submission).where(Submission.user_id == user.id).order_by(Submission.submitted_at)
    )
    ratings = await db.scalars(
        select(Rating).where(Rating.user_id == user.id).order_by(Rating.created_at)
    )
    comments = await db.scalars(
        select(RatingComment)
        .where(RatingComment.user_id == user.id)
        .order_by(RatingComment.created_at)
    )
    return {
        "profile": _dump(user),
        "submissions": [
            {
                "trackingId": s.tracking_id,
                "type": s.type,
                "channel": s.channel,
                "content": s.content,
                "url": s.url,
                "headline": s.headline,
                "language": s.language,
                "status": s.status,
                "submittedAt": s.submitted_at.isoformat(),
            }
            for s in submissions
        ],
        "ratings": [
            {"reportId": r.report_id, "vote": r.vote, "ratedAt": r.created_at.isoformat()}
            for r in ratings
        ],
        "comments": [
            {
                "reportId": c.report_id,
                "vote": c.vote,
                "body": c.body,
                "createdAt": c.created_at.isoformat(),
            }
            for c in comments
        ],
    }


# ---- Journalist / expert accreditation (FR-AUTH-02, FR-RATE-06) ----


@router.get("/me/verification", response_model=AccreditationStatus)
async def get_verification(
    user: UserProfile = Depends(_signed_in),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    app = (
        await db.scalars(
            select(AccreditationApplication)
            .where(AccreditationApplication.user_id == user.id)
            .order_by(AccreditationApplication.submitted_at.desc())
            .limit(1)
        )
    ).first()
    if app is None:
        return AccreditationStatus(status="none")
    return AccreditationStatus(
        status=app.status,
        role=app.requested_role,
        organisation=app.organisation,
        submitted_at=app.submitted_at,
        reviewed_at=app.reviewed_at,
        note=app.note,
    )


@router.post("/me/verification", status_code=202)
async def apply_for_verification(
    organisation: str = Form(...),
    documents: list[UploadFile] = File(...),  # noqa: B008
    press_card_number: str | None = Form(None, alias="pressCardNumber"),
    role: str = Form("journalist"),
    user: UserProfile = Depends(_signed_in),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Apply as a Verified Journalist or, from public or journalist, as an Expert Reviewer.
    An admin decides (POST /admin/verifications/{id}/decision)."""
    if role not in ACCREDITATION_ROLES:
        raise ApiError("bad_request", "role must be 'journalist' or 'expert'.")
    if user.role in ("expert", "admin") or user.role == role:
        raise ApiError("conflict", "Your account already has a verified role.")
    pending = (
        await db.execute(
            select(func.count()).where(
                AccreditationApplication.user_id == user.id,
                AccreditationApplication.status == "pending",
            )
        )
    ).scalar_one()
    if pending:
        raise ApiError("conflict", "You already have an application under review.")
    if not organisation.strip() or not documents:
        raise ApiError("bad_request", "Organisation and at least one document are required.")

    # Check every document before storing any, so a bad second file leaves nothing behind.
    files = []
    for doc in documents:
        content_type = doc.content_type or "application/octet-stream"
        if content_type not in _DOCUMENT_TYPES:
            raise ApiError("unsupported_media", "Upload a photo (JPEG, PNG, WebP) or a PDF.")
        data = await doc.read(rules.MAX_MEDIA_BYTES + 1)
        if len(data) > rules.MAX_MEDIA_BYTES:
            raise ApiError("file_too_large", "Each document must be under 50 MB.")
        files.append((data, content_type))

    app_id = new_id("acc")
    storage = get_object_storage()
    keys = []
    for i, (data, content_type) in enumerate(files):
        key = f"accreditation/{user.id}/{app_id}/{i}"
        await storage.put(key=key, data=data, content_type=content_type)
        keys.append(key)

    db.add(
        AccreditationApplication(
            id=app_id,
            user_id=user.id,
            status="pending",
            organisation=organisation.strip(),
            requested_role=role,
            press_card_number=(press_card_number or "").strip() or None,
            document_keys=keys,
        )
    )
    await db.commit()
    return {}


# ---- Activity (FR-SUBMIT-07, Activity page) ----

_ACTIVITY_STATUS = {"queued": "processing", "processing": "processing", "completed": "complete"}


@router.get("/me/submissions", response_model=None)
async def list_my_submissions(
    params: PageParams = Depends(page_params),  # noqa: B008
    user: UserProfile = Depends(_signed_in),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    where = Submission.user_id == user.id
    total = (await db.execute(select(func.count()).where(where))).scalar_one()
    rows = await db.execute(
        select(Submission, FactCheckReport)
        .outerjoin(FactCheckReport, FactCheckReport.tracking_id == Submission.tracking_id)
        .where(where)
        .order_by(Submission.submitted_at.desc())
        .offset((params.page - 1) * params.per_page)
        .limit(params.per_page)
    )
    items = [
        ActivitySubmission(
            tracking_id=s.tracking_id,
            type=s.type,
            preview=s.preview,
            submitted_at=s.submitted_at,
            status=_ACTIVITY_STATUS.get(s.status, "failed"),
            verdict=r.verdict if r else None,
            report_id=r.id if r else None,
        )
        for s, r in rows
    ]
    return {
        "data": [_dump(i) for i in items],
        "page": params.page,
        "perPage": params.per_page,
        "total": total,
    }


@router.get("/me/ratings", response_model=None)
async def list_my_ratings(
    params: PageParams = Depends(page_params),  # noqa: B008
    user: UserProfile = Depends(_signed_in),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    where = Rating.user_id == user.id
    total = (await db.execute(select(func.count()).where(where))).scalar_one()
    # The rating's comment, if the user left one on that report (their latest).
    comment = (
        select(RatingComment.body)
        .where(RatingComment.report_id == Rating.report_id, RatingComment.user_id == user.id)
        .where(RatingComment.removed_at.is_(None))
        .order_by(RatingComment.created_at.desc())
        .limit(1)
        .scalar_subquery()
    )
    rows = await db.execute(
        select(Rating, FactCheckReport, comment)
        .join(FactCheckReport, FactCheckReport.id == Rating.report_id)
        .where(where)
        .order_by(Rating.updated_at.desc())
        .offset((params.page - 1) * params.per_page)
        .limit(params.per_page)
    )
    items = [
        ActivityRating(
            report_id=r.id,
            title=r.title,
            verdict=r.verdict,
            vote=rating.vote,
            comment=body,
            rated_at=rating.updated_at,
        )
        for rating, r, body in rows
    ]
    return {
        "data": [_dump(i) for i in items],
        "page": params.page,
        "perPage": params.per_page,
        "total": total,
    }


@router.get("/me/api-usage")
async def get_api_usage(
    user: UserProfile = Depends(_signed_in),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Partner requests across all of my keys: this clock hour, and the last 24 hours."""
    now = datetime.now(UTC)
    this_hour = now.replace(minute=0, second=0, microsecond=0)

    async def total_since(since: datetime) -> int:
        return (
            await db.execute(
                select(func.coalesce(func.sum(ApiUsageHourly.count), 0))
                .join(ApiKey, ApiKey.id == ApiUsageHourly.api_key_id)
                .where(ApiKey.user_id == user.id, ApiUsageHourly.hour >= since)
            )
        ).scalar_one()

    return {
        "usedThisHour": await total_since(this_hour),
        "last24h": await total_since(this_hour - timedelta(hours=23)),
    }
