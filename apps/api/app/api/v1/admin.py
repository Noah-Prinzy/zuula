from datetime import UTC, datetime

from fastapi import Body, Depends, Query, Request, Response
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.adapters.clamav import ScanError, get_clamav_scanner
from app.adapters.storage import get_object_storage
from app.core.errors import ApiError
from app.core.pagination import PageParams, page_params
from app.core.router import APIRouter
from app.core.security import require_roles
from app.db.base import new_id
from app.db.models import AccreditationApplication as AccreditationApplicationRow
from app.db.models import (
    AuditLogEntry,
    ContentFlag,
    ContentReport,
    FactCheckReport,
    ManipulationSignal,
    Notification,
    Rating,
    RatingComment,
    User,
)
from app.db.models import Broadcast as BroadcastRow
from app.db.models import PlatformSettings as PlatformSettingsRow
from app.db.models import TrustedSource as TrustedSourceRow
from app.db.models.identity import ACCREDITATION_STATUSES
from app.db.session import get_db
from app.schemas.account import UserProfile
from app.schemas.admin import (
    AccreditationApplicant,
    AccreditationApplication,
    AccreditationApplicationDetail,
    AccreditationDocument,
    AdminOverview,
    AdminUser,
    AuditEntry,
    Broadcast,
    PlatformSettings,
    TrustedSource,
    TrustedSourceInput,
)
from app.schemas.admin import ContentReport as ContentReportSchema
from app.schemas.admin import ManipulationSignal as ManipulationSignalSchema
from app.services import (
    accreditation_documents,
    admin_metrics,
    audit,
    broadcasts,
    notifications,
    recompute,
)
from app.services.auth import revoke_sessions
from app.services.platform_settings import get_platform_settings
from app.worker import dispatch

router = APIRouter(prefix="/admin", tags=["admin"])

_admin = require_roles("admin")


def _dump(model) -> dict:
    return model.model_dump(by_alias=True, mode="json", exclude_none=True)


@router.get("/overview", response_model=AdminOverview)
async def get_admin_overview(
    user: UserProfile = Depends(_admin),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    return await admin_metrics.overview(db)


_ROLE_LABELS = {
    "public": "Public User",
    "journalist": "Verified Journalist",
    "expert": "Expert Reviewer",
    "admin": "Admin",
}


def _admin_user(u: User, ratings: int) -> AdminUser:
    return AdminUser(
        id=u.id,
        name=u.name,
        email=u.email or u.phone or "",
        role=u.role,
        status=u.status,
        joined=u.created_at.date(),
        last_active=(u.last_active_at or u.created_at).date(),
        ratings=ratings,
    )


def _ratings_count():
    return (
        select(func.count())
        .where(Rating.user_id == User.id, Rating.excluded_at.is_(None))
        .scalar_subquery()
    )


@router.get("/users", response_model=None)
async def list_admin_users(
    q: str | None = None,
    role: str | None = None,
    status: str | None = None,
    params: PageParams = Depends(page_params),  # noqa: B008
    user: UserProfile = Depends(_admin),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    conditions = [User.deleted_at.is_(None)]
    if q:
        needle = f"%{q.strip()}%"
        conditions.append(
            or_(User.name.ilike(needle), User.email.ilike(needle), User.phone.ilike(needle))
        )
    if role:
        conditions.append(User.role == role)
    if status:
        conditions.append(User.status == status)

    total = (
        await db.execute(select(func.count()).select_from(User).where(*conditions))
    ).scalar_one()
    rows = await db.execute(
        select(User, _ratings_count())
        .where(*conditions)
        .order_by(User.created_at, User.id)
        .offset((params.page - 1) * params.per_page)
        .limit(params.per_page)
    )
    return {
        "data": [_dump(_admin_user(u, n)) for u, n in rows],
        "page": params.page,
        "perPage": params.per_page,
        "total": total,
    }


@router.patch("/users/{id}", response_model=AdminUser)
async def update_admin_user(
    id: str,  # noqa: A002
    request: Request,
    body: dict = Body(...),  # noqa: B008
    user: UserProfile = Depends(_admin),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """FR-ADMIN-02: change a user's role or status. Takes effect on the user's very next request
    (roles are read from the database on every request), and every change is audited."""
    target = await db.get(User, id)
    if target is None or target.deleted_at is not None:
        raise ApiError("not_found", f"No user '{id}'.")
    new_role = body.get("role", target.role)
    new_status = body.get("status", target.status)
    if new_role not in _ROLE_LABELS or new_status not in ("active", "suspended", "pending"):
        raise ApiError("bad_request", "Unknown role or status.")
    changing = new_role != target.role or new_status != target.status
    if changing and target.id == user.id:
        # An admin locking themselves out (or demoting the last admin) is never intended.
        raise ApiError("bad_request", "You can't change your own role or status.")

    if new_role != target.role:
        audit.record(
            db,
            actor=user,
            action="user.role_change",
            target=target.name,
            detail=f"{_ROLE_LABELS[target.role]} → {_ROLE_LABELS[new_role]}",
            request=request,
        )
        target.role = new_role
    if new_status != target.status:
        if new_status == "suspended":
            audit.record(db, actor=user, action="user.suspend", target=target.name, request=request)
            await revoke_sessions(db, target.id)  # signed out everywhere, immediately
        elif target.status == "suspended":
            audit.record(
                db, actor=user, action="user.reinstate", target=target.name, request=request
            )
        target.status = new_status

    # Decision 6a: an admin can drop a user's past ratings from every score (and restore them).
    affected: list[str] = []
    if "excludeRatings" in body:
        exclude = body["excludeRatings"]
        if not isinstance(exclude, bool):
            raise ApiError("bad_request", "excludeRatings must be true or false.")
        affected = await recompute.set_ratings_excluded(db, target.id, exclude)
        if affected:
            audit.record(
                db,
                actor=user,
                action="ratings.exclude",
                target=target.name,
                detail=f"{'Dropped' if exclude else 'Restored'} {len(affected)} ratings",
                request=request,
            )
    await db.commit()
    if affected:
        await dispatch.dispatch_recompute(affected)

    ratings = (
        await db.execute(
            select(func.count()).where(Rating.user_id == target.id, Rating.excluded_at.is_(None))
        )
    ).scalar_one()
    return _admin_user(target, ratings)


# ---- Accreditation review (FR-AUTH-02) ----


def _applicant(u: User) -> AccreditationApplicant:
    return AccreditationApplicant(
        id=u.id,
        name=u.name,
        email=u.email or u.phone or "",
        role=u.role,
        status=u.status,
        district=u.district,
        joined=u.created_at.date(),
    )


def _application(
    a: AccreditationApplicationRow, applicant: User, reviewer: str | None
) -> AccreditationApplication:
    return AccreditationApplication(
        id=a.id,
        status=a.status,
        requested_role=a.requested_role,
        organisation=a.organisation,
        press_card_number=a.press_card_number,
        submitted_at=a.submitted_at,
        reviewed_at=a.reviewed_at,
        reviewer=reviewer,
        note=a.note,
        document_count=len(a.document_keys),
        applicant=_applicant(applicant),
    )


def _detail(
    a: AccreditationApplicationRow, applicant: User, reviewer: str | None
) -> AccreditationApplicationDetail:
    documents = []
    for index in range(len(a.document_keys)):
        url, expires_at = accreditation_documents.signed_path(a.id, index)
        documents.append(AccreditationDocument(index=index, url=url, expires_at=expires_at))
    return AccreditationApplicationDetail(
        **dict(_application(a, applicant, reviewer)), documents=documents
    )


_Reviewer = aliased(User)


def _with_people():
    return (
        select(AccreditationApplicationRow, User, _Reviewer.name)
        .join(User, User.id == AccreditationApplicationRow.user_id)
        .outerjoin(_Reviewer, _Reviewer.id == AccreditationApplicationRow.reviewer_id)
    )


@router.get("/verifications", response_model=None)
async def list_verifications(
    status: str | None = None,
    params: PageParams = Depends(page_params),  # noqa: B008
    user: UserProfile = Depends(_admin),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """The accreditation queue: pending applications oldest first, then decided ones, most
    recently decided first."""
    conditions = []
    if status:
        if status not in ACCREDITATION_STATUSES:
            raise ApiError("bad_request", "Unknown status.")
        conditions.append(AccreditationApplicationRow.status == status)
    total = (
        await db.execute(
            select(func.count()).select_from(AccreditationApplicationRow).where(*conditions)
        )
    ).scalar_one()
    rows = await db.execute(
        _with_people()
        .where(*conditions)
        .order_by(
            AccreditationApplicationRow.status != "pending",
            AccreditationApplicationRow.reviewed_at.desc().nulls_first(),
            AccreditationApplicationRow.submitted_at,
            AccreditationApplicationRow.id,
        )
        .offset((params.page - 1) * params.per_page)
        .limit(params.per_page)
    )
    return {
        "data": [_dump(_application(a, u, reviewer)) for a, u, reviewer in rows],
        "page": params.page,
        "perPage": params.per_page,
        "total": total,
    }


@router.get("/verifications/{id}", response_model=None)
async def get_verification_application(
    id: str,  # noqa: A002
    user: UserProfile = Depends(_admin),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """One application, with its applicant and short-lived links to its documents."""
    row = (await db.execute(_with_people().where(AccreditationApplicationRow.id == id))).first()
    if row is None:
        raise ApiError("not_found", f"No application '{id}'.")
    return _dump(_detail(*row))


@router.get("/verifications/{id}/documents/{index}", response_model=None)
async def download_verification_document(
    id: str,  # noqa: A002
    index: int,
    expires: int = Query(...),
    sig: str = Query(...),
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """A signed link from GET /admin/verifications/{id}: the signature is the credential (see
    app/services/accreditation_documents.py). The file is virus-scanned before it's served."""
    if not accreditation_documents.link_valid(id, index, expires, sig):
        raise ApiError("forbidden", "This link has expired. Reopen the application.")
    application = await db.get(AccreditationApplicationRow, id)
    if application is None or not 0 <= index < len(application.document_keys):
        raise ApiError("not_found", "No such document.")
    data = await get_object_storage().get(key=application.document_keys[index])
    try:
        scan = await get_clamav_scanner().scan(data)
    except ScanError as exc:
        # Fail closed: an unscanned document is never handed out.
        raise ApiError("server_error", "Couldn't scan this document. Try again later.") from exc
    if not scan.clean:
        raise ApiError(
            "invalid_content", f"This document failed the virus scan ({scan.signature})."
        )
    content_type, ext = accreditation_documents.sniff(data)
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": f'inline; filename="{id}-{index + 1}.{ext}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/verifications/{id}/decision", response_model=None)
async def decide_verification(
    id: str,  # noqa: A002
    request: Request,
    body: dict = Body(...),  # noqa: B008
    user: UserProfile = Depends(_admin),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Approve (the applicant gets the role they applied for, effective on their next request)
    or reject with a note. Audited, and the applicant is told in-app and by email."""
    decision = body.get("decision")
    note = (body.get("note") or "").strip()
    if decision not in ("approve", "reject"):
        raise ApiError("bad_request", "decision must be 'approve' or 'reject'.")
    if decision == "reject" and len(note) < 5:
        raise ApiError("bad_request", "Say why the application is rejected; the applicant sees it.")

    application = (
        await db.scalars(
            select(AccreditationApplicationRow)
            .where(AccreditationApplicationRow.id == id)
            .with_for_update()
        )
    ).first()
    if application is None:
        raise ApiError("not_found", f"No application '{id}'.")
    if application.status != "pending":
        raise ApiError("conflict", "This application has already been decided.")
    applicant = await db.get(User, application.user_id)
    if applicant is None or applicant.deleted_at is not None:
        raise ApiError("conflict", "The applicant's account has been deleted.")
    if applicant.id == user.id:
        raise ApiError("bad_request", "You can't decide your own application.")

    requested = _ROLE_LABELS[application.requested_role]
    if decision == "approve":
        if applicant.role == "admin":
            raise ApiError("conflict", "The applicant is an admin; change their role directly.")
        organisation = f" ({application.organisation})" if application.organisation else ""
        audit.record(
            db,
            actor=user,
            action="accreditation.approve",
            target=applicant.name,
            detail=f"{_ROLE_LABELS[applicant.role]} → {requested}{organisation}",
            request=request,
        )
        applicant.role = application.requested_role
        title = "Accreditation approved"
        message = f"Your application to become a {requested} was approved."
    else:
        audit.record(
            db,
            actor=user,
            action="accreditation.reject",
            target=applicant.name,
            detail=f"{requested}: {note}",
            request=request,
        )
        title = "Accreditation not approved"
        message = f"Your application to become a {requested} wasn't approved: {note}"
    # "pending" marks an account awaiting accreditation; decided either way, it's active.
    if applicant.status == "pending":
        applicant.status = "active"
    application.status = "approved" if decision == "approve" else "rejected"
    application.reviewed_at = datetime.now(UTC)
    application.reviewer_id = user.id
    application.note = note or None
    notifications.notify(
        db,
        user_id=applicant.id,
        kind="accreditation",
        title=title,
        body=message,
        href="/account/verification",
    )
    await db.commit()
    if applicant.email:
        await dispatch.dispatch_message("email", applicant.email, message, f"Zuula: {title}")
    return _dump(_detail(application, applicant, user.name))


# ---- Moderation (FR-RATE-07, FR-ADMIN) ----


def _flag_count():
    return (
        select(func.count())
        .where(ContentFlag.content_report_id == ContentReport.id)
        .scalar_subquery()
    )


@router.get("/moderation/reports", response_model=None)
async def list_content_reports(
    params: PageParams = Depends(page_params),  # noqa: B008
    user: UserProfile = Depends(_admin),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Open reader reports, most reported first."""
    open_items = ContentReport.resolved_at.is_(None)
    total = (await db.execute(select(func.count()).where(open_items))).scalar_one()
    rows = await db.execute(
        select(ContentReport, FactCheckReport.title, _flag_count())
        .join(FactCheckReport, FactCheckReport.id == ContentReport.report_id)
        .where(open_items)
        .order_by(_flag_count().desc(), ContentReport.reported_at.desc())
        .offset((params.page - 1) * params.per_page)
        .limit(params.per_page)
    )
    items = [
        ContentReportSchema(
            id=c.id,
            report_id=c.report_id,
            title=title,
            reason=c.reason,
            reporters=reporters,
            sample=c.sample,
            reported_at=c.reported_at,
        )
        for c, title, reporters in rows
    ]
    return {
        "data": [_dump(i) for i in items],
        "page": params.page,
        "perPage": params.per_page,
        "total": total,
    }


@router.post("/moderation/reports/{id}/resolve")
async def resolve_content_report(
    id: str,  # noqa: A002
    request: Request,
    body: dict = Body(...),  # noqa: B008
    user: UserProfile = Depends(_admin),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """`dismiss` closes the item. `remove` also hides the rating comments it was about (a
    verdict itself is never removed — disputed verdicts go to expert review instead)."""
    action = body.get("action")
    if action not in ("dismiss", "remove"):
        raise ApiError("bad_request", "action must be 'dismiss' or 'remove'.")
    item = await db.get(ContentReport, id)
    if item is None or item.resolved_at is not None:
        raise ApiError("not_found", f"No open report '{id}'.")

    now = datetime.now(UTC)
    if action == "remove":
        comment_ids = set(
            await db.scalars(
                select(ContentFlag.comment_id).where(
                    ContentFlag.content_report_id == item.id, ContentFlag.comment_id.is_not(None)
                )
            )
        )
        if not comment_ids:
            raise ApiError(
                "bad_request", "Nothing to remove: these reports are about the verdict itself."
            )
        await db.execute(
            update(RatingComment)
            .where(RatingComment.id.in_(comment_ids), RatingComment.removed_at.is_(None))
            .values(removed_at=now, removed_by=user.id)
        )
        note = (body.get("note") or "").strip()
        audit.record(
            db,
            actor=user,
            action="moderation.remove",
            target=f"Comment on {item.report_id}",
            detail=note or item.reason,
            request=request,
        )
    item.resolved_at = now
    item.resolution = action
    item.resolved_by = user.id
    await db.commit()
    return {}


@router.get("/moderation/signals", response_model=list)
async def list_manipulation_signals(
    user: UserProfile = Depends(_admin),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Suspected coordinated rating (app/services/brigading.py), newest first."""
    rows = await db.execute(
        select(ManipulationSignal, FactCheckReport.title)
        .join(FactCheckReport, FactCheckReport.id == ManipulationSignal.report_id)
        .where(ManipulationSignal.resolved_at.is_(None))
        .order_by(ManipulationSignal.detected_at.desc())
    )
    return [
        _dump(
            ManipulationSignalSchema(
                id=m.id,
                report_id=m.report_id,
                title=title,
                pattern=m.pattern,
                accounts=m.accounts,
                window=m.window,
                direction=m.direction,
                confidence=m.confidence,
            )
        )
        for m, title in rows
    ]


# ---- Trusted sources (FR-DETECT-06) ----

_SOURCE_TYPE_LABELS = {
    "media": "Media house",
    "government": "Government",
    "fact-checker": "Fact-checker",
    "international": "International",
    "academic": "Academic",
}


def _source_of(s: TrustedSourceRow) -> TrustedSource:
    return TrustedSource(
        id=s.id,
        name=s.name,
        domain=s.domain,
        type=s.type,
        languages=s.languages,
        tier=s.tier,
        active=s.active,
        # Until the crawler's first run, the contract's required lastCrawled is when it was added.
        last_crawled=s.last_crawled or s.created_at,
        crawl_ok=s.crawl_ok,
    )


def _domain(raw: str) -> str:
    domain = raw.strip().lower().removeprefix("https://").removeprefix("http://")
    return domain.split("/")[0].removeprefix("www.")


async def _domain_taken(db: AsyncSession, domain: str, except_id: str | None = None) -> bool:
    query = select(TrustedSourceRow.id).where(TrustedSourceRow.domain == domain)
    if except_id:
        query = query.where(TrustedSourceRow.id != except_id)
    return (await db.scalars(query)).first() is not None


@router.get("/sources", response_model=None)
async def list_sources(
    params: PageParams = Depends(page_params),  # noqa: B008
    user: UserProfile = Depends(_admin),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    total = (await db.execute(select(func.count()).select_from(TrustedSourceRow))).scalar_one()
    rows = await db.scalars(
        select(TrustedSourceRow)
        .order_by(TrustedSourceRow.active.desc(), TrustedSourceRow.tier, TrustedSourceRow.name)
        .offset((params.page - 1) * params.per_page)
        .limit(params.per_page)
    )
    return {
        "data": [_dump(_source_of(s)) for s in rows],
        "page": params.page,
        "perPage": params.per_page,
        "total": total,
    }


@router.post("/sources", response_model=TrustedSource, status_code=201)
async def add_source(
    body: TrustedSourceInput,
    request: Request,
    user: UserProfile = Depends(_admin),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    domain = _domain(body.domain)
    if await _domain_taken(db, domain):
        raise ApiError("conflict", f"{domain} is already a trusted source.")
    source = TrustedSourceRow(
        id=new_id("src"),
        name=body.name.strip(),
        domain=domain,
        type=body.type,
        languages=body.languages,
        tier=body.tier,
        active=body.active,
        crawl_ok=True,
        created_at=datetime.now(UTC),
    )
    db.add(source)
    audit.record(
        db,
        actor=user,
        action="source.add",
        target=source.name,
        detail=f"{_SOURCE_TYPE_LABELS[body.type]}, {', '.join(body.languages)}, tier {body.tier}",
        request=request,
    )
    await db.commit()
    return _source_of(source)


async def _get_source(db: AsyncSession, source_id: str) -> TrustedSourceRow:
    source = await db.get(TrustedSourceRow, source_id)
    if source is None:
        raise ApiError("not_found", f"No source '{source_id}'.")
    return source


def _audit_deactivation(db, user, source, request, detail: str) -> None:
    audit.record(
        db,
        actor=user,
        action="source.deactivate",
        target=source.name,
        detail=detail,
        request=request,
    )


@router.patch("/sources/{id}", response_model=TrustedSource)
async def update_source(
    id: str,  # noqa: A002
    body: TrustedSourceInput,
    request: Request,
    user: UserProfile = Depends(_admin),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    source = await _get_source(db, id)
    domain = _domain(body.domain)
    if await _domain_taken(db, domain, except_id=source.id):
        raise ApiError("conflict", f"{domain} is already a trusted source.")
    if source.active and not body.active:
        _audit_deactivation(db, user, source, request, "Deactivated")
    source.name = body.name.strip()
    source.domain = domain
    source.type = body.type
    source.languages = body.languages
    source.tier = body.tier
    source.active = body.active
    await db.commit()
    return _source_of(source)


@router.delete("/sources/{id}", status_code=204)
async def remove_source(
    id: str,  # noqa: A002
    request: Request,
    user: UserProfile = Depends(_admin),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Deactivated, not deleted: past reports cite this source, so the record stays."""
    source = await _get_source(db, id)
    if source.active:
        source.active = False
        _audit_deactivation(db, user, source, request, "Removed from active sources")
        await db.commit()
    return None


# ---- Broadcasts (FR-NOTIFY, FR-ADMIN) ----


def _opened():
    return (
        select(func.count())
        .where(Notification.broadcast_id == BroadcastRow.id, Notification.read_at.is_not(None))
        .scalar_subquery()
    )


def _broadcast_of(b: BroadcastRow, sender: str, opened: int) -> Broadcast:
    return Broadcast(
        id=b.id,
        title=b.title,
        message=b.message,
        severity=b.severity,
        audience=b.audience,
        channels=b.channels,
        sent_at=b.sent_at,
        sent_by=sender,
        reach=b.reach,
        # Seeded sample broadcasts carry their own figure; real ones count read notifications.
        opened=max(opened, b.opened),
    )


@router.get("/broadcasts", response_model=list[Broadcast])
async def list_broadcasts(
    user: UserProfile = Depends(_admin),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    rows = await db.execute(
        select(BroadcastRow, User.name, _opened())
        .join(User, User.id == BroadcastRow.sent_by)
        .order_by(BroadcastRow.sent_at.desc())
    )
    return [_broadcast_of(b, name, opened) for b, name, opened in rows]


@router.post("/broadcasts", response_model=Broadcast, status_code=202)
async def send_broadcast(
    request: Request,
    body: dict = Body(...),  # noqa: B008
    user: UserProfile = Depends(_admin),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Everyone gets it in-app at once; SMS/email follow from the worker, to people who have
    those channels on (app/services/broadcasts.py)."""
    for field in ("title", "message", "severity", "audience"):
        if not str(body.get(field) or "").strip():
            raise ApiError("bad_request", f"{field} is required.")
    channels = body.get("channels")
    if not isinstance(channels, list) or not channels:
        raise ApiError("bad_request", "Choose at least one channel.")
    if body["severity"] not in ("high", "critical"):
        raise ApiError("bad_request", "severity must be 'high' or 'critical'.")

    broadcast = BroadcastRow(
        id=new_id("bc"),
        title=body["title"].strip(),
        message=body["message"].strip(),
        severity=body["severity"],
        audience=body["audience"].strip(),
        channels=[str(c) for c in channels],
        sent_at=datetime.now(UTC),
        sent_by=user.id,
    )
    db.add(broadcast)
    await db.flush()
    broadcast.reach = await broadcasts.fan_out_in_app(db, broadcast)
    audit.record(
        db,
        actor=user,
        action="broadcast.send",
        target=broadcast.id,
        detail=f"{broadcast.title} ({broadcast.audience})",
        request=request,
    )
    await db.commit()
    await dispatch.dispatch_broadcast(broadcast.id)
    return _broadcast_of(broadcast, user.name, 0)


@router.get("/reports", response_model=list)
async def list_monthly_reports(
    user: UserProfile = Depends(_admin),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    return [_dump(r) for r in await admin_metrics.monthly_reports(db)]


@router.get("/audit-log", response_model=None)
async def list_audit_log(
    actor_role: str | None = Query(None, alias="actorRole"),
    action: str | None = None,
    params: PageParams = Depends(page_params),  # noqa: B008
    user: UserProfile = Depends(_admin),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    conditions = []
    if actor_role:
        conditions.append(AuditLogEntry.actor_role == actor_role)
    if action:
        conditions.append(AuditLogEntry.action == action)
    total = (
        await db.execute(select(func.count()).select_from(AuditLogEntry).where(*conditions))
    ).scalar_one()
    rows = await db.scalars(
        select(AuditLogEntry)
        .where(*conditions)
        .order_by(AuditLogEntry.at.desc(), AuditLogEntry.id.desc())
        .offset((params.page - 1) * params.per_page)
        .limit(params.per_page)
    )
    entries = [
        AuditEntry(
            id=f"a{e.id}",
            at=e.at,
            actor=e.actor_name,
            actor_role=e.actor_role,
            action=e.action,
            target=e.target,
            detail=e.detail,
            ip=e.ip,
        )
        for e in rows
    ]
    return {
        "data": [_dump(e) for e in entries],
        "page": params.page,
        "perPage": params.per_page,
        "total": total,
    }


# ---- Platform settings (FR-ADMIN-06) ----


def _validate_settings(settings: PlatformSettings) -> None:
    t, w = settings.thresholds, settings.weights
    problems = []
    if not (0 <= t.suspended_max < t.escalated_max < t.questioned_min <= t.questioned_max):
        problems.append("score bands must run suspended < escalated < questioned")
    if not (t.questioned_max < t.verified_min <= 100):
        problems.append("verified must start above the questioned band, at most 100")
    if min(t.questioned_ratings, t.escalated_ratings, t.suspended_ratings) < 1:
        problems.append("rating minimums must be at least 1")
    if min(w.public, w.journalist, w.expert) < 1:
        problems.append("weights must be at least 1")
    if settings.sla_hours < 1 or settings.api_rate_limit < 1:
        problems.append("SLA hours and API rate limit must be at least 1")
    if not 0 <= settings.retraining.min_ccs <= 100:
        problems.append("retraining minimum CCS must be 0–100")
    if problems:
        raise ApiError("bad_request", "Invalid settings: " + "; ".join(problems) + ".")


_THRESHOLD_LABELS = {
    "verified_min": "Verified: min score",
    "questioned_min": "Questioned: min score",
    "questioned_max": "Questioned: max score",
    "questioned_ratings": "Questioned: min ratings",
    "escalated_max": "Escalated: max score",
    "escalated_ratings": "Escalated: min ratings",
    "suspended_max": "Suspended: max score",
    "suspended_ratings": "Suspended: min ratings",
}


def _changes(before: PlatformSettings, after: PlatformSettings) -> list[str]:
    """Human-readable diff for the audit log, e.g. "Questioned: min ratings 40 → 50"."""
    out = []
    for field, label in _THRESHOLD_LABELS.items():
        old, new = getattr(before.thresholds, field), getattr(after.thresholds, field)
        if old != new:
            out.append(f"{label} {old} → {new}")
    for role in ("public", "journalist", "expert"):
        old, new = getattr(before.weights, role), getattr(after.weights, role)
        if old != new:
            out.append(f"{role.capitalize()} weight {old}× → {new}×")
    if before.sla_hours != after.sla_hours:
        out.append(f"Review SLA {before.sla_hours} h → {after.sla_hours} h")
    if before.api_rate_limit != after.api_rate_limit:
        out.append(f"API rate limit {before.api_rate_limit} → {after.api_rate_limit}/hour")
    if before.retraining != after.retraining:
        out.append("Retraining schedule changed")
    return out


@router.get("/settings", response_model=PlatformSettings)
async def get_platform_settings_route(
    user: UserProfile = Depends(_admin),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    return await get_platform_settings(db)


@router.patch("/settings", response_model=PlatformSettings)
async def update_platform_settings(
    body: PlatformSettings,
    request: Request,
    user: UserProfile = Depends(_admin),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Saves the settings and audits what changed. If the weights or thresholds changed, every
    report's score is recomputed in the background, and reports that newly cross into
    escalated or suspended get review cases (decision 6b)."""
    _validate_settings(body)
    before = await get_platform_settings(db)
    changes = _changes(before, body)
    if not changes:
        return before

    row = await db.get(PlatformSettingsRow, 1)
    data = _dump(body)
    if row is None:
        db.add(PlatformSettingsRow(id=1, settings=data, updated_by=user.id))
    else:
        row.settings = data
        row.updated_at = datetime.now(UTC)
        row.updated_by = user.id
    audit.record(
        db,
        actor=user,
        action="settings.update",
        target="Platform settings",
        detail="; ".join(changes),
        request=request,
    )
    await db.commit()
    if before.weights != body.weights or before.thresholds != body.thresholds:
        await dispatch.dispatch_recompute(None)
    return body
