"""Library search, facets, the home feed, a full report and related reports (FR-SEARCH,
FR-RATE-10), from the database. Every list excludes suspended reports (app.services.reports
LISTED)."""

from datetime import date, datetime, timedelta

from fastapi import Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.core.router import APIRouter
from app.core.security import get_current_user
from app.db.models import FactCheckReport
from app.db.session import get_db
from app.schemas.account import UserProfile
from app.schemas.common import ContentType
from app.schemas.fact_check import FactCheckSummary, dump_report
from app.services import reports as rep
from app.services.platform_settings import get_platform_settings

router = APIRouter(prefix="/fact-checks", tags=["fact-checks"])

_KAMPALA = "Africa/Kampala"
_TOTAL_RATINGS = (
    FactCheckReport.accurate_public
    + FactCheckReport.accurate_journalist
    + FactCheckReport.accurate_expert
    + FactCheckReport.inaccurate_public
    + FactCheckReport.inaccurate_journalist
    + FactCheckReport.inaccurate_expert
)
# Library dates are Uganda dates: a check at 01:00 EAT on the 22nd is "the 22nd".
CHECKED_ON = func.date(func.timezone(_KAMPALA, FactCheckReport.checked_at))


def _dump(model) -> dict:
    return model.model_dump(by_alias=True, mode="json", exclude_none=True)


def parse_date(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ApiError("bad_request", f"{name} must be a date (YYYY-MM-DD).") from exc


# FR-RATE-10 leaderboard: at least this many ratings to qualify (apps/web/lib/library.ts).
LEADERBOARD_MIN_RATINGS = 25


def _agreement_lower_bound(settings, z: float = 1.96):
    """apps/web/lib/library.ts's agreementLowerBound(), in SQL: the lower bound of the 95%
    Wilson interval around the weighted CCS share over the number of people who rated. It
    rewards agreement and volume together, so 26 ratings at 100% don't outrank 424 at 99%."""
    w = settings.weights
    r = FactCheckReport
    accurate = r.accurate_public * w.public + r.accurate_journalist * w.journalist
    accurate = accurate + r.accurate_expert * w.expert
    inaccurate = r.inaccurate_public * w.public + r.inaccurate_journalist * w.journalist
    inaccurate = inaccurate + r.inaccurate_expert * w.expert
    n = func.nullif(_TOTAL_RATINGS, 0) * 1.0
    p = accurate * 1.0 / func.nullif(accurate + inaccurate, 0)
    z2 = z * z
    bound = (p + z2 / (2 * n) - z * func.sqrt((p * (1 - p) + z2 / (4 * n)) / n)) / (1 + z2 / n)
    return func.coalesce(bound, 0)


def text_match(q: str):
    """Every word must match (the P2/Library behaviour): full-text over title, summary,
    category and submitted text, with a fuzzy title match for typos and partial words."""
    return or_(
        FactCheckReport.search_tsv.op("@@")(func.plainto_tsquery("simple", q)),
        FactCheckReport.title.ilike(f"%{q}%"),
    )


@router.get("", response_model=None)
async def search_fact_checks(
    q: str = "",
    verdict: str = Query("", description="Comma-separated Verdict values"),
    category: str | None = None,
    language: str | None = None,
    type: ContentType | None = None,  # noqa: A002 — the contract's query param name
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    sort: str = Query("relevance", pattern="^(relevance|newest|most-rated)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(12, ge=1, le=50, alias="perPage"),
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    conditions = [rep.LISTED]
    if q.strip():
        conditions.append(text_match(q.strip()))
    verdicts = [v for v in verdict.split(",") if v]
    if verdicts:
        conditions.append(FactCheckReport.verdict.in_(verdicts))
    if category:
        conditions.append(FactCheckReport.category == category)
    if language:
        conditions.append(FactCheckReport.language == language)
    if type:
        conditions.append(FactCheckReport.content_type == type)
    if (start := parse_date(from_, "from")) is not None:
        conditions.append(start <= CHECKED_ON)
    if (end := parse_date(to, "to")) is not None:
        conditions.append(end >= CHECKED_ON)

    order = {
        "newest": [FactCheckReport.checked_at.desc()],
        "most-rated": [_TOTAL_RATINGS.desc(), FactCheckReport.checked_at.desc()],
        "relevance": [rep.relevance_expr().desc(), FactCheckReport.checked_at.desc()],
    }[sort]

    total = (
        await db.execute(select(func.count()).select_from(FactCheckReport).where(*conditions))
    ).scalar_one()
    rows = await db.scalars(
        select(FactCheckReport)
        .where(*conditions)
        .order_by(*order)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    settings = await get_platform_settings(db)
    return {
        "data": [_dump(rep.summary_of(r, settings)) for r in rows],
        "page": page,
        "perPage": per_page,
        "total": total,
    }


@router.get("/facets", response_model=None)
async def get_facets(db: AsyncSession = Depends(get_db)):  # noqa: B008
    categories = await db.scalars(
        select(FactCheckReport.category)
        .where(rep.LISTED)
        .distinct()
        .order_by(FactCheckReport.category)
    )
    languages = await db.scalars(
        select(FactCheckReport.language)
        .where(rep.LISTED)
        .distinct()
        .order_by(FactCheckReport.language)
    )
    return {"categories": list(categories), "languages": list(languages)}


@router.get("/home-feed", response_model=None)
async def get_home_feed(db: AsyncSession = Depends(get_db)):  # noqa: B008
    """The Home page (FR-RATE-10): newest checks, the most debated (many ratings, CCS near
    50), trending categories this week, and the community leaderboard (the verdicts the
    community most confidently agrees with — apps/web/lib/library.ts's leaderboard())."""
    settings = await get_platform_settings(db)

    recent = list(
        await db.scalars(
            select(FactCheckReport)
            .where(rep.LISTED)
            .order_by(FactCheckReport.checked_at.desc())
            .limit(5)
        )
    )
    recent_ids = [r.id for r in recent]

    debate = _TOTAL_RATINGS * (1 - func.abs(FactCheckReport.ccs - 50) / 50.0)
    debated = await db.scalars(
        select(FactCheckReport)
        .where(rep.LISTED, FactCheckReport.ccs.is_not(None), FactCheckReport.id.not_in(recent_ids))
        .order_by(debate.desc(), FactCheckReport.checked_at.desc())
        .limit(3)
    )

    leaders = await db.scalars(
        select(FactCheckReport)
        .where(
            rep.LISTED,
            FactCheckReport.ccs.is_not(None),
            _TOTAL_RATINGS >= LEADERBOARD_MIN_RATINGS,
        )
        .order_by(_agreement_lower_bound(settings).desc(), _TOTAL_RATINGS.desc())
        .limit(5)
    )

    week_ago = datetime.now().astimezone() - timedelta(days=7)
    trending = await db.execute(
        select(FactCheckReport.category, func.count())
        .where(rep.LISTED, FactCheckReport.checked_at >= week_ago)
        .group_by(FactCheckReport.category)
        .order_by(func.count().desc(), FactCheckReport.category)
        .limit(6)
    )

    return {
        "recent": [_dump(rep.summary_of(r, settings)) for r in recent],
        "debated": [_dump(rep.summary_of(r, settings)) for r in debated],
        "trending": [{"category": c, "count": n} for c, n in trending],
        "leaderboard": [
            {
                "report": _dump(rep.summary_of(r, settings)),
                "score": _dump(rep.score_of(r, settings)),
            }
            for r in leaders
        ],
    }


async def get_report_row(db: AsyncSession, report_id: str) -> FactCheckReport:
    row = await db.get(FactCheckReport, report_id)
    if row is None:
        raise ApiError("not_found", f"No fact-check with id '{report_id}'.")
    return row


@router.get("/{id}", response_model=None)
async def get_fact_check(
    id: str,  # noqa: A002
    db: AsyncSession = Depends(get_db),  # noqa: B008
    user: UserProfile | None = Depends(get_current_user),  # noqa: B008
):
    # Direct links work even for suspended reports; only listings hide them. Optional auth
    # (get_current_user) so community.myVote can reflect the viewer's own vote when signed in,
    # without requiring sign-in just to read a report.
    row = await get_report_row(db, id)
    return dump_report(await rep.full_report(db, row, viewer_id=user.id if user else None))


@router.get("/{id}/related", response_model=list[FactCheckSummary])
async def get_related(
    id: str,  # noqa: A002
    limit: int = Query(3, ge=1, le=10),
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """FR-SEARCH-03: semantic similarity (pgvector cosine distance) where embeddings exist,
    topped up with the Library's lexical match for reports without one."""
    report = await get_report_row(db, id)
    settings = await get_platform_settings(db)
    found: list[FactCheckReport] = []
    if report.embedding is not None:
        found = list(
            await db.scalars(
                select(FactCheckReport)
                .where(
                    rep.LISTED,
                    FactCheckReport.id != report.id,
                    FactCheckReport.embedding.is_not(None),
                )
                .order_by(FactCheckReport.embedding.cosine_distance(report.embedding))
                .limit(limit)
            )
        )
    if len(found) < limit:
        # Candidates for the lexical match: the same category plus the most recent checks.
        taken = [report.id, *(r.id for r in found)]
        candidates = list(
            await db.scalars(
                select(FactCheckReport)
                .where(rep.LISTED, FactCheckReport.id.not_in(taken))
                .order_by(
                    (FactCheckReport.category == report.category).desc(),
                    FactCheckReport.checked_at.desc(),
                )
                .limit(500)
            )
        )
        found += rep.lexical_related(report, candidates, limit - len(found))
    return [rep.summary_of(r, settings) for r in found]
