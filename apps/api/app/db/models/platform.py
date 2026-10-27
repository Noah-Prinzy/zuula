"""Admin-managed platform state: trusted sources, broadcasts, notifications, settings and the
audit log (FR-ADMIN, FR-NOTIFY). ADR 0002 §2."""

from datetime import datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, in_check
from app.db.models.identity import ROLES

SOURCE_TYPES = ("media", "government", "fact-checker", "international", "academic")


class TrustedSource(Base):
    __tablename__ = "trusted_sources"
    __table_args__ = (
        CheckConstraint(in_check("type", SOURCE_TYPES), name="type"),
        CheckConstraint("tier BETWEEN 1 AND 3", name="tier"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(Text, unique=True)
    type: Mapped[str] = mapped_column(Text)
    languages: Mapped[list[str]] = mapped_column(ARRAY(Text))
    tier: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    # Written by the source crawler (P4); NULL until its first run.
    last_crawled: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    crawl_ok: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = created_at_column()


class Broadcast(Base):
    __tablename__ = "broadcasts"
    __table_args__ = (CheckConstraint(in_check("severity", ("high", "critical")), name="severity"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text)
    audience: Mapped[str] = mapped_column(Text)
    channels: Mapped[list[str]] = mapped_column(ARRAY(Text))
    sent_at: Mapped[datetime] = created_at_column()
    sent_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reach: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    opened: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


NOTIFICATION_KINDS = (
    "verdict-ready",
    "topic-alert",
    "review-outcome",
    "broadcast",
    "accreditation",
)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(in_check("kind", NOTIFICATION_KINDS), name="kind"),
        Index("ix_notifications_user_created", "user_id", text("created_at DESC")),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    href: Mapped[str | None] = mapped_column(Text)
    broadcast_id: Mapped[str | None] = mapped_column(ForeignKey("broadcasts.id"))
    created_at: Mapped[datetime] = created_at_column()
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AlertSettings(Base):
    """A user's AlertSettings document, stored whole (it's only ever read and written whole)."""

    __tablename__ = "alert_settings"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    settings: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = created_at_column()


class PlatformSettings(Base):
    """The one row of admin-editable settings (FR-ADMIN-06): the contract's PlatformSettings,
    seeded from app/core/rules.py. The CHECK keeps it a singleton."""

    __tablename__ = "platform_settings"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False, default=1)
    settings: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = created_at_column()
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


AUDIT_ACTIONS = (
    "verdict.override",
    "verdict.confirm",
    "user.role_change",
    "user.suspend",
    "user.reinstate",  # lifting a suspension (P3 PR 2; no P2 action covered it)
    "ratings.exclude",  # dropping/restoring a user's past ratings (P3 PR 4, decision 6a)
    "source.add",
    "source.deactivate",
    "broadcast.send",
    "settings.update",
    "moderation.remove",
    "accreditation.approve",  # an admin approving or rejecting an accreditation application
    "accreditation.reject",
)


class AuditLogEntry(Base):
    """FR-ADMIN-07 / FR-REVIEW-03. Append-only: the migration installs a trigger that rejects
    UPDATE and DELETE on this table. `actor_name`/`actor_role` are copied at write time so
    an entry still reads correctly after the actor is renamed, promoted or anonymised.

    `ip` is text, not inet, because it's stored already truncated (`196.43.x.x`, the shape
    the contract and admin screen show): §10.1 data minimisation — the full address is never
    kept."""

    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint(in_check("action", AUDIT_ACTIONS), name="action"),
        CheckConstraint(in_check("actor_role", ROLES), name="actor_role"),
        Index("ix_audit_log_at", text("at DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    at: Mapped[datetime] = created_at_column()
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    actor_name: Mapped[str] = mapped_column(Text)
    actor_role: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text, index=True)
    target: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text, default="", server_default="")
    ip: Mapped[str] = mapped_column(Text, default="", server_default="")


class ModelEvaluation(Base):
    """AI accuracy figures for the admin KPIs that can't be derived from platform data (text
    F1, deepfake accuracy). P4's evaluation runs write these; seeded until then."""

    __tablename__ = "model_evaluations"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    metric: Mapped[str] = mapped_column(Text, index=True)  # the Kpi id, e.g. "f1"
    value: Mapped[float] = mapped_column(Float)
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    model_version: Mapped[str | None] = mapped_column(Text)
    evaluated_at: Mapped[datetime] = created_at_column()
