"""Submissions, fact-check reports and community ratings (FR-SUBMIT, FR-DETECT, FR-RATE).
ADR 0002 §2–§4."""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, in_check

SUBMISSION_TYPES = ("text", "url", "media", "article")
SUBMISSION_CHANNELS = ("web", "partner", "whatsapp", "telegram")
SUBMISSION_STATUSES = ("queued", "processing", "completed", "failed")
CONTENT_TYPES = ("text", "url", "image", "audio", "video")
VERDICTS = ("authentic", "likely-false", "false", "ai-generated", "unverifiable")
COMMUNITY_STATUSES = ("verified", "standard", "questioned", "escalated", "suspended")
VOTES = ("accurate", "inaccurate")
RATER_ROLES = ("public", "journalist", "expert")


class Submission(Base):
    """One thing someone asked Zuula to check, from any channel. Replaces P2's TTL'd Redis
    state blob (app/realtime/submissions.py); Redis keeps only the live pub/sub."""

    __tablename__ = "submissions"
    __table_args__ = (
        CheckConstraint(in_check("type", SUBMISSION_TYPES), name="type"),
        CheckConstraint(in_check("channel", SUBMISSION_CHANNELS), name="channel"),
        CheckConstraint(in_check("status", SUBMISSION_STATUSES), name="status"),
        # openapi.yaml TrackingId: ^ZL-[A-Z2-9]{4}-[A-Z2-9]{2}$
        CheckConstraint("tracking_id ~ '^ZL-[A-Z2-9]{4}-[A-Z2-9]{2}$'", name="tracking_id"),
        # Idempotency-Key is scoped to whoever sent it (a signed-in user or a partner key).
        Index(
            "uq_submissions_user_idempotency",
            "user_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL AND idempotency_key IS NOT NULL"),
        ),
        Index(
            "uq_submissions_api_key_idempotency",
            "api_key_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("api_key_id IS NOT NULL AND idempotency_key IS NOT NULL"),
        ),
    )

    tracking_id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    api_key_id: Mapped[str | None] = mapped_column(ForeignKey("api_keys.id"), index=True)
    channel: Mapped[str] = mapped_column(Text, default="web", server_default="web")
    # WhatsApp phone number / Telegram chat id to send the verdict back to (FR-SUBMIT-04).
    channel_ref: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    headline: Mapped[str | None] = mapped_column(Text)
    article_url: Mapped[str | None] = mapped_column(Text)
    media_object_key: Mapped[str | None] = mapped_column(Text)  # S3 key
    media_content_type: Mapped[str | None] = mapped_column(Text)
    media_bytes: Mapped[int | None] = mapped_column(Integer)
    language: Mapped[str] = mapped_column(Text, default="auto", server_default="auto")
    preview: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(Text, default="queued", server_default="queued")
    # [{step, status, seconds?}] — the SubmissionStepEvent list the Status page renders.
    steps: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    submitted_at: Mapped[datetime] = created_at_column()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[dict | None] = mapped_column(JSONB)  # an ErrorEnvelope
    idempotency_key: Mapped[str | None] = mapped_column(Text)


# `simple` config: Postgres has no stemmer for Luganda, Acholi, Runyankole or Ateso, so every
# language gets the same token-level treatment (ADR 0002 §1).
_SEARCH_TSV = (
    "to_tsvector('simple'::regconfig, "
    "coalesce(title, '') || ' ' || coalesce(summary, '') || ' ' || "
    "coalesce(category, '') || ' ' || coalesce(submitted_text, ''))"
)


class FactCheckReport(Base):
    """A finished check. Claims, citations and AI signals are the pipeline's output, written
    once and always read whole, so they're JSONB rather than child tables. Community counts
    are denormalized here and recomputed from `ratings` in the same transaction as every vote
    (ADR 0002 §4), so list endpoints never aggregate ratings on the fly."""

    __tablename__ = "fact_check_reports"
    __table_args__ = (
        CheckConstraint(in_check("content_type", CONTENT_TYPES), name="content_type"),
        CheckConstraint(in_check("verdict", VERDICTS), name="verdict"),
        CheckConstraint(in_check("community_status", COMMUNITY_STATUSES), name="community_status"),
        CheckConstraint("confidence BETWEEN 0 AND 100", name="confidence"),
        CheckConstraint("ccs IS NULL OR ccs BETWEEN 0 AND 100", name="ccs"),
        Index("ix_fact_check_reports_search_tsv", "search_tsv", postgresql_using="gin"),
        Index(
            "ix_fact_check_reports_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index("ix_fact_check_reports_checked_at", text("checked_at DESC")),
        Index(
            "ix_fact_check_reports_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # fc-YYYY-NNNN
    tracking_id: Mapped[str] = mapped_column(ForeignKey("submissions.tracking_id"), unique=True)
    title: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text)  # display name, e.g. "Luganda" (the contract's)
    submitted_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    source_url: Mapped[str | None] = mapped_column(Text)
    source_host: Mapped[str | None] = mapped_column(Text, index=True)  # for "same source" ranking
    verdict: Mapped[str] = mapped_column(Text, index=True)
    confidence: Mapped[int] = mapped_column(Integer)
    summary: Mapped[str] = mapped_column(Text)
    what_is_false: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default=text("'{}'::text[]")
    )
    what_is_true: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default=text("'{}'::text[]")
    )
    claims: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    citations: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    ai_signals: Mapped[list] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    category: Mapped[str] = mapped_column(Text, index=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processing_seconds: Mapped[float] = mapped_column(Float)
    human_review: Mapped[dict | None] = mapped_column(JSONB)  # the contract's HumanReview

    accurate_public: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    accurate_journalist: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    accurate_expert: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    inaccurate_public: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    inaccurate_journalist: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    inaccurate_expert: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    ccs: Mapped[int | None] = mapped_column(Integer)
    community_status: Mapped[str] = mapped_column(
        Text, default="standard", server_default="standard", index=True
    )
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # FR-SEARCH-03 related reports, and the P4 dedupe check (app/providers/analysis.py's
    # GroqAnalysisProvider): all-MiniLM-L6-v2 (app/providers/embedding.py), 384 dimensions.
    # migrations/versions/0004_embedding_dimensions.py narrows this from the untyped
    # vector P3 shipped and adds the HNSW index below.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384))
    search_tsv: Mapped[str] = mapped_column(TSVECTOR, Computed(_SEARCH_TSV, persisted=True))


class ExpertAnnotation(Base):
    __tablename__ = "expert_annotations"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    report_id: Mapped[str] = mapped_column(ForeignKey("fact_check_reports.id"), index=True)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    author_title: Mapped[str] = mapped_column(Text)  # the contract's `role` label
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()


class Rating(Base):
    """One person's vote on one report. `rater_role` is the role they voted with, not their
    current one (ADR 0002 §4, 6a) — a later promotion doesn't silently re-weight old votes.
    `excluded_at` is how an admin drops a suspended or de-accredited user's past votes from
    every score without deleting the evidence (an audited action)."""

    __tablename__ = "ratings"
    __table_args__ = (
        PrimaryKeyConstraint("report_id", "user_id"),
        CheckConstraint(in_check("vote", VOTES), name="vote"),
        CheckConstraint(in_check("rater_role", RATER_ROLES), name="rater_role"),
    )

    report_id: Mapped[str] = mapped_column(ForeignKey("fact_check_reports.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    vote: Mapped[str] = mapped_column(Text)
    rater_role: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = created_at_column()
    excluded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RatingComment(Base):
    __tablename__ = "rating_comments"
    __table_args__ = (
        CheckConstraint(in_check("vote", VOTES), name="vote"),
        CheckConstraint(in_check("rater_role", RATER_ROLES), name="rater_role"),
        Index("ix_rating_comments_report_created", "report_id", text("created_at DESC")),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    report_id: Mapped[str] = mapped_column(ForeignKey("fact_check_reports.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    vote: Mapped[str] = mapped_column(Text)
    rater_role: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
    # Moderation (FR-ADMIN, audit action `moderation.remove`): hidden, not deleted.
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
