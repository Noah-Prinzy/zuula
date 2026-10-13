"""Expert review (FR-REVIEW-01…06): the queue, a case, assignment and decisions. Expert and
Admin only. Cases are opened by app/services/escalation.py (community escalation,
suspension, user reports, low AI confidence). ADR 0002 §4.

A decision closes the case, records the reviewer's verdict on the report (`humanReview`, and
the new verdict when overridden), writes the audit log (FR-REVIEW-03) and tells the report's
raters. It does not relist a suspended report: that takes the score recovering (decision 7).
"""

from datetime import UTC, datetime, timedelta

from fastapi import Body, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rules
from app.core.errors import ApiError
from app.core.pagination import PageParams, page_params
from app.core.router import APIRouter
from app.core.security import require_roles
from app.db.base import new_id
from app.db.models import ContentFlag, FactCheckReport, Rating, ReviewCase, ReviewDecision, User
from app.db.session import get_db
from app.schemas.account import UserProfile
from app.schemas.fact_check import dump_report
from app.schemas.review import ReviewCase as CaseSchema
from app.schemas.review import ReviewDecision as DecisionSchema
from app.schemas.review import dump_review_case
from app.services import audit, notifications
from app.services.notifications import VERDICT_LABELS
from app.services.reports import full_report

router = APIRouter(prefix="/review", tags=["review"])

# FR-REVIEW: Expert, Admin only.
_REVIEWERS = ("expert", "admin")
_reviewer = require_roles(*_REVIEWERS)


def _sla_state(due: datetime, now: datetime) -> str:
    hours_left = (due - now).total_seconds() / 3600
    if hours_left < 0:
        return "overdue"
    return "due-soon" if hours_left < rules.REVIEW_DUE_SOON_HOURS else "on-track"


def _flag_count():
    return (
        select(func.count())
        .where(ContentFlag.content_report_id == ReviewCase.content_report_id)
        .scalar_subquery()
    )


def _case_query():
    return select(ReviewCase, User.name, _flag_count()).outerjoin(
        User, User.id == ReviewCase.assignee_id
    )


def _case_of(case: ReviewCase, assignee: str | None, flags: int, now: datetime) -> dict:
    return dump_review_case(
        CaseSchema(
            id=case.id,
            report_id=case.report_id,
            reason=case.reason,
            flagged_at=case.flagged_at,
            reports=flags if case.content_report_id else None,
            assignee=assignee,
            priority=case.priority,
            sla_due_at=case.sla_due_at,
            sla_state=_sla_state(case.sla_due_at, now) if case.status == "open" else None,
        )
    )


def _decision_of(d: ReviewDecision, title: str, reviewer: str) -> DecisionSchema:
    return DecisionSchema(
        id=d.id,
        case_id=d.case_id,
        report_id=d.report_id,
        title=title,
        outcome=d.outcome,
        **{"from": d.from_verdict},
        to=d.to_verdict,
        justification=d.justification,
        reviewer=reviewer,
        decided_at=d.decided_at,
        turnaround_hours=d.turnaround_hours,
    )


def _decisions_query():
    return (
        select(ReviewDecision, FactCheckReport.title, User.name)
        .join(FactCheckReport, FactCheckReport.id == ReviewDecision.report_id)
        .join(User, User.id == ReviewDecision.reviewer_id)
        .order_by(ReviewDecision.decided_at.desc())
    )


def _dump(model) -> dict:
    return model.model_dump(by_alias=True, mode="json", exclude_none=True)


@router.get("/overview")
async def get_review_overview(
    user: UserProfile = Depends(_reviewer),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    now = datetime.now(UTC)
    open_case = ReviewCase.status == "open"
    queue = (await db.execute(select(func.count()).where(open_case))).scalar_one()
    overdue = (
        await db.execute(select(func.count()).where(open_case, ReviewCase.sla_due_at < now))
    ).scalar_one()
    due_soon = (
        await db.execute(
            select(func.count()).where(
                open_case,
                ReviewCase.sla_due_at >= now,
                ReviewCase.sla_due_at < now + timedelta(hours=rules.REVIEW_DUE_SOON_HOURS),
            )
        )
    ).scalar_one()
    recent = await db.execute(_decisions_query().limit(5))
    return {
        "queueSize": queue,
        "overdue": overdue,
        "dueSoon": due_soon,
        "recentDecisions": [_dump(_decision_of(d, t, r)) for d, t, r in recent],
    }


@router.get("/queue", response_model=None)
async def get_review_queue(
    reason: str | None = None,
    assignee: str | None = None,
    params: PageParams = Depends(page_params),  # noqa: B008
    user: UserProfile = Depends(_reviewer),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Open cases, most urgent first (FR-REVIEW-06): high priority, then the nearest SLA."""
    conditions = [ReviewCase.status == "open"]
    if reason:
        conditions.append(ReviewCase.reason == reason)
    if assignee == "unassigned":
        conditions.append(ReviewCase.assignee_id.is_(None))
    elif assignee == "me":
        conditions.append(ReviewCase.assignee_id == user.id)
    elif assignee:
        conditions.append(User.name == assignee)

    count_query = (
        select(func.count())
        .select_from(ReviewCase)
        .outerjoin(User, User.id == ReviewCase.assignee_id)
        .where(*conditions)
    )
    total = (await db.execute(count_query)).scalar_one()
    rows = await db.execute(
        _case_query()
        .where(*conditions)
        .order_by((ReviewCase.priority == "high").desc(), ReviewCase.sla_due_at)
        .offset((params.page - 1) * params.per_page)
        .limit(params.per_page)
    )
    now = datetime.now(UTC)
    return {
        "data": [_case_of(c, name, flags, now) for c, name, flags in rows],
        "page": params.page,
        "perPage": params.per_page,
        "total": total,
    }


async def _load_case(db: AsyncSession, case_id: str, *, lock: bool = False):
    query = _case_query().where(ReviewCase.id == case_id)
    if lock:
        query = query.with_for_update(of=ReviewCase)
    row = (await db.execute(query)).first()
    if row is None:
        raise ApiError("not_found", f"No review case '{case_id}'.")
    return row


@router.get("/cases/{id}", response_model=None)
async def get_review_case(
    id: str,  # noqa: A002
    user: UserProfile = Depends(_reviewer),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    case, assignee, flags = await _load_case(db, id)
    report = await db.get(FactCheckReport, case.report_id)
    return {
        "case": _case_of(case, assignee, flags, datetime.now(UTC)),
        "report": dump_report(await full_report(db, report, viewer_id=user.id)) if report else None,
    }


@router.post("/cases/{id}/assign", response_model=None)
async def assign_case(
    id: str,  # noqa: A002
    body: dict = Body(...),  # noqa: B008
    user: UserProfile = Depends(_reviewer),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Assign to `assigneeId` (a reviewer's user id), or to yourself when it's omitted."""
    case, _, flags = await _load_case(db, id, lock=True)
    assignee_id = body.get("assigneeId") or user.id
    assignee = await db.get(User, assignee_id)
    if assignee is None or assignee.role not in _REVIEWERS or assignee.status == "suspended":
        raise ApiError("not_found", f"No reviewer '{assignee_id}'.")
    case.assignee_id = assignee.id
    await db.commit()
    return _case_of(case, assignee.name, flags, datetime.now(UTC))


def _excerpt(text: str, words: int = 5) -> str:
    parts = text.split()
    return " ".join(parts[:words]) + ("…" if len(parts) > words else "")


@router.post("/cases/{id}/decision", response_model=DecisionSchema)
async def decide_case(
    id: str,  # noqa: A002
    request: Request,
    body: dict = Body(...),  # noqa: B008
    user: UserProfile = Depends(_reviewer),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    outcome = body.get("outcome")
    justification = (body.get("justification") or "").strip()
    if outcome not in ("confirmed", "overridden") or len(justification) < (
        rules.REVIEW_JUSTIFICATION_MIN
    ):
        raise ApiError(
            "bad_request",
            "outcome and a justification of at least "
            f"{rules.REVIEW_JUSTIFICATION_MIN} characters are required.",
        )

    case, _, _ = await _load_case(db, id, lock=True)
    if case.status != "open":
        raise ApiError("conflict", "This case has already been decided.")
    report = (
        await db.scalars(
            select(FactCheckReport).where(FactCheckReport.id == case.report_id).with_for_update()
        )
    ).one()

    previous = report.verdict
    verdict = body.get("verdict") if outcome == "overridden" else previous
    if outcome == "overridden" and verdict not in VERDICT_LABELS:
        raise ApiError("bad_request", "A valid verdict is required when overriding.")

    now = datetime.now(UTC)
    report.verdict = verdict
    report.human_review = {
        "outcome": outcome,
        "reviewer": user.name,
        "reviewedAt": now.isoformat(),
        "justification": justification,
        **({"previousVerdict": previous} if outcome == "overridden" else {}),
    }
    case.status = "decided"
    case.closed_at = now
    decision = ReviewDecision(
        id=new_id("dec"),
        case_id=case.id,
        report_id=report.id,
        outcome=outcome,
        from_verdict=previous,
        to_verdict=verdict,
        justification=justification,
        reviewer_id=user.id,
        decided_at=now,
        turnaround_hours=round((now - case.flagged_at).total_seconds() / 3600, 1),
    )
    db.add(decision)

    # FR-REVIEW-03, in the admin screen's own wording ("False → Likely False: “…”").
    if outcome == "overridden":
        detail = (
            f"{VERDICT_LABELS[previous]} → {VERDICT_LABELS[verdict]}: “{_excerpt(justification)}”"
        )
        action = "verdict.override"
    else:
        detail = f"{VERDICT_LABELS[previous]} confirmed: “{_excerpt(justification)}”"
        action = "verdict.confirm"
    audit.record(db, actor=user, action=action, target=report.id, detail=detail, request=request)

    # Everyone who rated this verdict hears the outcome (the "review-outcome" notification).
    body_text = (
        "An Expert Reviewer confirmed the original verdict."
        if outcome == "confirmed"
        else f"An Expert Reviewer changed the verdict to {VERDICT_LABELS[verdict]}."
    )
    raters = await db.scalars(
        select(Rating.user_id).where(Rating.report_id == report.id, Rating.user_id != user.id)
    )
    for rater in raters:
        notifications.notify(
            db,
            user_id=rater,
            kind="review-outcome",
            title="A verdict you rated was reviewed",
            body=body_text,
            href=f"/fact-checks/{report.id}",
        )
    await db.commit()
    return _decision_of(decision, report.title, user.name)


@router.get("/history", response_model=None)
async def get_review_history(
    params: PageParams = Depends(page_params),  # noqa: B008
    user: UserProfile = Depends(_reviewer),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """My past decisions, newest first."""
    mine = ReviewDecision.reviewer_id == user.id
    total = (await db.execute(select(func.count()).where(mine))).scalar_one()
    rows = await db.execute(
        _decisions_query()
        .where(mine)
        .offset((params.page - 1) * params.per_page)
        .limit(params.per_page)
    )
    return {
        "data": [_dump(_decision_of(d, t, r)) for d, t, r in rows],
        "page": params.page,
        "perPage": params.per_page,
        "total": total,
    }
