from datetime import datetime

from app.schemas.common import (
    CamelModel,
    CitationStance,
    ClaimAssessment,
    ContentType,
    RaterRole,
    Verdict,
)


class Claim(CamelModel):
    id: str
    start: int
    end: int
    assessment: ClaimAssessment
    reason: str
    citation_ids: list[str]


class Citation(CamelModel):
    id: str
    source_name: str
    title: str
    url: str
    published_at: str  # ISO date
    stance: CitationStance
    trusted: bool
    excerpt: str | None = None


class AISignal(CamelModel):
    id: str
    label: str
    description: str
    score: float
    threshold: float
    method: str


class ExpertAnnotation(CamelModel):
    id: str
    author: str
    role: str
    created_at: datetime
    body: str


class HumanReview(CamelModel):
    outcome: str  # "confirmed" | "overridden"
    reviewer: str
    reviewed_at: datetime
    previous_verdict: Verdict | None = None
    justification: str


class RatingCounts(CamelModel):
    public: int
    journalist: int
    expert: int


class RatingComment(CamelModel):
    id: str
    author: str
    role: RaterRole
    vote: str  # "accurate" | "inaccurate"
    body: str
    created_at: datetime


class CommunityScore(CamelModel):
    """Computed server-side (§9.1 weights, §9.2 thresholds) — never trust a client-sent value."""

    ccs: float | None
    weighted_accurate: float
    weighted_inaccurate: float
    accurate_count: int
    inaccurate_count: int
    total: int
    status: str  # verified | standard | questioned | escalated | suspended


class PublicCommunityCounts(CamelModel):
    accurate: RatingCounts
    inaccurate: RatingCounts


class CommunityRating(CamelModel):
    accurate: RatingCounts
    inaccurate: RatingCounts
    comments: list[RatingComment]
    score: CommunityScore
    # The signed-in viewer's own current vote (None if unrated or no one is signed in) — see
    # app.services.reports.full_report()'s viewer_id parameter.
    my_vote: str | None = None


class FactCheckReport(CamelModel):
    """Full report — core API only (includes submittedText, annotations and comments)."""

    id: str
    tracking_id: str
    title: str
    content_type: ContentType
    language: str
    submitted_text: str
    source_url: str | None = None
    verdict: Verdict
    confidence: int
    summary: str
    what_is_false: list[str]
    what_is_true: list[str]
    claims: list[Claim]
    citations: list[Citation]
    ai_signals: list[AISignal]
    annotations: list[ExpertAnnotation]
    human_review: HumanReview | None = None
    community: CommunityRating
    category: str
    checked_at: datetime
    processing_seconds: float


class FactCheckSummary(CamelModel):
    """List-item shape for /fact-checks search, the Home feed and related reports (core API)."""

    id: str
    tracking_id: str
    title: str
    content_type: ContentType
    language: str
    verdict: Verdict
    confidence: int
    summary: str
    category: str
    checked_at: datetime
    score: CommunityScore


class FactCheckPublic(CamelModel):
    """Partner-facing report shape (GET /v1/fact-checks/{id}). Matches the `factCheck()` helper
    in apps/web/components/developers/examples.ts exactly: no submittedText, no annotations,
    no rating comments — only aggregate community counts."""

    id: str
    tracking_id: str
    url: str
    title: str
    content_type: ContentType
    language: str
    category: str
    verdict: Verdict
    confidence: int
    summary: str
    what_is_false: list[str]
    what_is_true: list[str]
    claims: list[Claim]
    citations: list[Citation]
    ai_signals: list[AISignal]
    community: PublicCommunityCounts
    human_review: HumanReview | None = None
    checked_at: datetime
    processing_seconds: float


class FactCheckSearchItem(CamelModel):
    """Partner search result item (GET /v1/fact-checks) — matches SEARCH_RESPONSE in examples.ts."""

    id: str
    tracking_id: str
    url: str
    title: str
    verdict: Verdict
    confidence: int
    summary: str
    category: str
    language: str
    checked_at: datetime


def dump_report(model: FactCheckReport | FactCheckPublic) -> dict:
    """Optional fields (sourceUrl, a citation's excerpt, humanReview.previousVerdict, ...) are
    omitted from the JSON entirely when unset, matching apps/web/lib/types/fact-check.ts's
    `field?: T` (optional-absent) rather than emitting an explicit null for every one of them —
    that would need every such field marked nullable in openapi.yaml for no real benefit.

    Two fields are the exception, both required-and-nullable in openapi.yaml (`oneOf: [T,
    null]`) rather than optional-absent, so exclude_none must not be allowed to drop them:

    - `humanReview`: examples.ts always includes it, explicitly falling back to `null`
      (`r.humanReview ?? null`), so the partner docs' documented shape has the key always
      present.
    - `community.score.ccs` (FactCheckReport only — FactCheckPublic's community field is the
      simplified PublicCommunityCounts, with no `score` at all): null until a report has its
      first rating (community_score() in app/services/community.py), which every seeded sample
      report already has, but a freshly created one (app/worker/pipeline.py) doesn't.
    """
    data = model.model_dump(by_alias=True, mode="json", exclude_none=True)
    data.setdefault("humanReview", None)
    if "score" in data.get("community", {}):
        data["community"]["score"].setdefault("ccs", None)
    return data
