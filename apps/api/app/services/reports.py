"""Fact-check reports from the database, in the contract's shapes (FactCheckReport,
FactCheckSummary, FactCheckPublic, FactCheckSearchItem), plus the listing rules every read
path shares. ADR 0002 §2–§4.

"Listed" = not suspended (§9.2, FR-SEARCH): suspended reports are hidden from search, facets,
the home feed, related reports and partner search, and stay hidden for as long as they're
suspended — a review decision alone doesn't relist them (decision 7). The report page itself
stays reachable by direct link.
"""

import re
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ExpertAnnotation, FactCheckReport, Rating, RatingComment, User
from app.schemas.admin import PlatformSettings
from app.schemas.fact_check import (
    CommunityRating,
    CommunityScore,
    FactCheckPublic,
    FactCheckSearchItem,
    FactCheckSummary,
    HumanReview,
    PublicCommunityCounts,
)
from app.schemas.fact_check import ExpertAnnotation as AnnotationSchema
from app.schemas.fact_check import (
    FactCheckReport as ReportSchema,
)
from app.schemas.fact_check import RatingComment as CommentSchema
from app.services.community import report_counts
from app.services.platform_settings import get_platform_settings

PUBLIC_BASE_URL = "https://zuula.ug"
# How many rating comments a full report embeds (newest first). The rest are paged through
# GET /fact-checks/{id}/comments.
REPORT_COMMENTS = 20

LISTED = FactCheckReport.community_status != "suspended"


def score_of(row: FactCheckReport, settings: PlatformSettings) -> CommunityScore:
    """The report's CommunityScore from its stored counts, CCS and status (kept current by
    app.services.community.recompute_report_community), weighted with the live weights."""
    accurate, inaccurate = report_counts(row)
    w = settings.weights

    def weighted(c):
        return c.public * w.public + c.journalist * w.journalist + c.expert * w.expert

    accurate_count = accurate.public + accurate.journalist + accurate.expert
    inaccurate_count = inaccurate.public + inaccurate.journalist + inaccurate.expert
    return CommunityScore(
        ccs=row.ccs,
        weighted_accurate=weighted(accurate),
        weighted_inaccurate=weighted(inaccurate),
        accurate_count=accurate_count,
        inaccurate_count=inaccurate_count,
        total=accurate_count + inaccurate_count,
        status=row.community_status,
    )


def summary_of(row: FactCheckReport, settings: PlatformSettings) -> FactCheckSummary:
    return FactCheckSummary(
        id=row.id,
        tracking_id=row.tracking_id,
        title=row.title,
        content_type=row.content_type,
        language=row.language,
        verdict=row.verdict,
        confidence=row.confidence,
        summary=row.summary,
        category=row.category,
        checked_at=row.checked_at,
        score=score_of(row, settings),
    )


async def full_report(
    db: AsyncSession,
    row: FactCheckReport,
    settings: PlatformSettings | None = None,
    viewer_id: str | None = None,
) -> ReportSchema:
    settings = settings or await get_platform_settings(db)
    my_vote = (await db.get(Rating, (row.id, viewer_id))) if viewer_id else None
    annotations = (
        await db.execute(
            select(ExpertAnnotation, User.name)
            .join(User, User.id == ExpertAnnotation.author_id)
            .where(ExpertAnnotation.report_id == row.id)
            .order_by(ExpertAnnotation.created_at)
        )
    ).all()
    comments = (
        await db.execute(
            select(RatingComment, User.name)
            .join(User, User.id == RatingComment.user_id)
            .where(RatingComment.report_id == row.id, RatingComment.removed_at.is_(None))
            .order_by(RatingComment.created_at.desc())
            .limit(REPORT_COMMENTS)
        )
    ).all()
    accurate, inaccurate = report_counts(row)
    return ReportSchema(
        id=row.id,
        tracking_id=row.tracking_id,
        title=row.title,
        content_type=row.content_type,
        language=row.language,
        submitted_text=row.submitted_text,
        source_url=row.source_url,
        verdict=row.verdict,
        confidence=row.confidence,
        summary=row.summary,
        what_is_false=row.what_is_false,
        what_is_true=row.what_is_true,
        claims=row.claims,
        citations=row.citations,
        ai_signals=row.ai_signals,
        annotations=[
            AnnotationSchema(
                id=a.id, author=name, role=a.author_title, created_at=a.created_at, body=a.body
            )
            for a, name in annotations
        ],
        human_review=HumanReview.model_validate(row.human_review) if row.human_review else None,
        community=CommunityRating(
            accurate=accurate,
            inaccurate=inaccurate,
            comments=[comment_of(c, name) for c, name in comments],
            score=score_of(row, settings),
            my_vote=my_vote.vote if my_vote else None,
        ),
        category=row.category,
        checked_at=row.checked_at,
        processing_seconds=row.processing_seconds,
    )


def comment_of(c: RatingComment, author: str) -> CommentSchema:
    return CommentSchema(
        id=c.id, author=author, role=c.rater_role, vote=c.vote, body=c.body, created_at=c.created_at
    )


async def public_report(db: AsyncSession, row: FactCheckReport) -> FactCheckPublic:
    """The partner-facing shape (apps/web/components/developers/examples.ts's factCheck()):
    no submitted text, annotations or comments — only aggregate counts."""
    full = await full_report(db, row)
    return FactCheckPublic(
        id=row.id,
        tracking_id=row.tracking_id,
        url=f"{PUBLIC_BASE_URL}/fact-checks/{row.id}",
        title=row.title,
        content_type=row.content_type,
        language=row.language,
        category=row.category,
        verdict=row.verdict,
        confidence=row.confidence,
        summary=row.summary,
        what_is_false=full.what_is_false,
        what_is_true=full.what_is_true,
        claims=full.claims,
        citations=full.citations,
        ai_signals=full.ai_signals,
        community=PublicCommunityCounts(
            accurate=full.community.accurate, inaccurate=full.community.inaccurate
        ),
        human_review=full.human_review,
        checked_at=row.checked_at,
        processing_seconds=row.processing_seconds,
    )


def search_item_of(row: FactCheckReport) -> FactCheckSearchItem:
    return FactCheckSearchItem(
        id=row.id,
        tracking_id=row.tracking_id,
        url=f"{PUBLIC_BASE_URL}/fact-checks/{row.id}",
        title=row.title,
        verdict=row.verdict,
        confidence=row.confidence,
        summary=row.summary,
        category=row.category,
        language=row.language,
        checked_at=row.checked_at,
    )


# ---- Related reports (FR-SEARCH-03) ----
# A port of apps/web/lib/library.ts's relatedReports(): the lexical fallback for reports
# with no embedding yet (the embedding model is P4's; until then every report falls back).

_STOP_WORDS = set(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "will",
        "with",
    ]
)
_WORD_SPLIT = re.compile(r"[\W_]+")  # JS: /[^\p{L}\p{N}]+/u


def _keywords(row: FactCheckReport) -> set[str]:
    words = _WORD_SPLIT.split(f"{row.title} {row.summary}".lower())
    return {w for w in words if len(w) > 2 and w not in _STOP_WORDS}


def _host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        host = urlparse(url).hostname
    except ValueError:
        return None
    return host.removeprefix("www.") if host else None


def lexical_related(
    report: FactCheckReport, candidates: list[FactCheckReport], n: int
) -> list[FactCheckReport]:
    words = _keywords(report)
    domain = _host(report.source_url)
    scored = []
    for r in candidates:
        if r.id == report.id:
            continue
        other = _keywords(r)
        shared = len(words & other)
        overlap = shared / max(1, min(len(words), len(other)))
        same_topic = r.category == report.category
        same_source = bool(domain and _host(r.source_url) == domain)
        score = (
            (3 if same_topic else 0)
            + 4 * overlap
            + (1.5 if same_source else 0)
            + (0.5 if r.language == report.language else 0)
            + (0.25 if r.verdict == report.verdict else 0)
        )
        # Language and verdict only break ties; a match needs a shared topic, source or wording.
        if same_topic or same_source or overlap >= 0.2:
            scored.append((score, r))
    scored.sort(key=lambda x: (x[0], x[1].checked_at), reverse=True)
    return [r for _, r in scored[:n]]


def relevance_expr():
    """The Library's default ordering (P2's _rank, from apps/web/lib/library.ts): community
    confidence blended with a two-week recency decay, as SQL so the database sorts."""
    age_days = func.greatest(
        0, func.extract("epoch", func.now() - FactCheckReport.checked_at) / 86_400
    )
    return 0.6 * func.coalesce(FactCheckReport.ccs, 50) / 100.0 + 0.4 * func.exp(-age_days / 14)
