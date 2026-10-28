"""Users, sign-in and API credentials (FR-AUTH, FR-API-02). ADR 0002 §2 and §5."""

from datetime import datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, in_check

ROLES = ("public", "journalist", "expert", "admin")
USER_STATUSES = ("active", "suspended", "pending")
LOCALES = ("en", "lg", "ach", "nyn", "teo")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(in_check("role", ROLES), name="role"),
        CheckConstraint(in_check("status", USER_STATUSES), name="status"),
        CheckConstraint(
            f"preferred_language IS NULL OR {in_check('preferred_language', LOCALES)}",
            name="preferred_language",
        ),
        # An account signs in by email or phone (FR-AUTH-01) — it needs at least one.
        CheckConstraint("email IS NOT NULL OR phone IS NOT NULL", name="has_identifier"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    # Stored lower-cased by the auth service; unique so one identifier = one account.
    email: Mapped[str | None] = mapped_column(Text, unique=True)
    phone: Mapped[str | None] = mapped_column(Text, unique=True)  # E.164
    # Supabase Auth user id (the access token's `sub`), set on first Supabase sign-in. NULL for
    # accounts that have only used the legacy session sign-in. See app/core/supabase_auth.py.
    supabase_user_id: Mapped[str | None] = mapped_column(Text, unique=True)
    # NULL for accounts created through OAuth that never set a password.
    password_hash: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, default="public", server_default="public")
    status: Mapped[str] = mapped_column(Text, default="active", server_default="active")
    preferred_language: Mapped[str | None] = mapped_column(Text)
    district: Mapped[str | None] = mapped_column(Text)
    two_factor_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # §10.1 erasure (DELETE /me): the row is anonymised and kept, never hard-deleted, so the
    # audit log and ratings that reference it stay intact.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OAuthIdentity(Base):
    __tablename__ = "oauth_identities"
    __table_args__ = (
        UniqueConstraint("provider", "subject"),
        CheckConstraint(in_check("provider", ("google", "facebook")), name="provider"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text)  # the provider's stable user id
    email: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()


class Session(Base):
    """A signed-in device. The cookie/bearer value is never stored — only its SHA-256."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    device: Mapped[str] = mapped_column(Text, default="Unknown device")
    ip: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
    last_active_at: Mapped[datetime] = created_at_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


CHALLENGE_PURPOSES = ("signup", "two_factor", "password_reset")


class AuthChallenge(Base):
    """A one-time code sent by SMS or email (FR-AUTH-03/05, password reset). The code itself
    is never stored — only an HMAC of it keyed by ZUULA_SECRET_KEY."""

    __tablename__ = "auth_challenges"
    __table_args__ = (
        CheckConstraint(in_check("purpose", CHALLENGE_PURPOSES), name="purpose"),
        CheckConstraint(in_check("channel", ("sms", "email")), name="channel"),
        CheckConstraint("user_id IS NOT NULL OR payload IS NOT NULL", name="has_subject"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    # NULL for a sign-up: the account doesn't exist until the code is confirmed, so the
    # submitted name/identifier/password hash wait in `payload`. For a two-factor sign-in,
    # `payload` carries the `remember` choice through to the session it creates.
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    purpose: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(Text)
    destination: Mapped[str] = mapped_column(Text)  # the email/phone the code went to
    code_hash: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = created_at_column()
    last_sent_at: Mapped[datetime] = created_at_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


ACCREDITATION_STATUSES = ("pending", "approved", "rejected")
ACCREDITATION_ROLES = ("journalist", "expert")


class AccreditationApplication(Base):
    """A Verified Journalist or Expert Reviewer accreditation request (FR-AUTH-02). An admin
    approving one gives the user `requested_role` — an audited role change."""

    __tablename__ = "accreditation_applications"
    __table_args__ = (
        CheckConstraint(in_check("status", ACCREDITATION_STATUSES), name="status"),
        CheckConstraint(in_check("requested_role", ACCREDITATION_ROLES), name="requested_role"),
        # At most one application under consideration per user.
        Index(
            "uq_accreditation_applications_pending_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(Text, default="pending", server_default="pending")
    requested_role: Mapped[str] = mapped_column(
        Text, default="journalist", server_default="journalist"
    )
    organisation: Mapped[str | None] = mapped_column(Text)
    press_card_number: Mapped[str | None] = mapped_column(Text)
    # S3 object keys of the uploaded press card / ID documents (openapi.yaml `documents`).
    document_keys: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default=text("'{}'::text[]")
    )
    submitted_at: Mapped[datetime] = created_at_column()
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(Text)


API_SCOPES = ("submit", "read")


class ApiKey(Base):
    """A partner API key (FR-API-02). The secret is 128 random bits, so a fast SHA-256 is
    enough — there's nothing to brute-force the way there is with a human password."""

    __tablename__ = "api_keys"
    __table_args__ = (CheckConstraint("scopes <@ ARRAY['submit','read']::text[]", name="scopes"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(Text)
    prefix: Mapped[str] = mapped_column(Text, index=True)  # `zl_live_4f7a`, shown in the UI
    secret_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text))
    created_at: Mapped[datetime] = created_at_column()
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApiUsageHourly(Base):
    """Partner requests per key per hour, flushed from the Redis rate-limit counter. Backs
    GET /me/api-usage and the admin "API partners" KPI."""

    __tablename__ = "api_usage_hourly"

    api_key_id: Mapped[str] = mapped_column(ForeignKey("api_keys.id"), primary_key=True)
    hour: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
