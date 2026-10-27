"""Enums and a shared base model. Mirrors apps/api/openapi.yaml's components.schemas — keep
these two in sync by hand; a future step could generate this file from the contract the way
packages/shared generates TS types, but P2 Step 2 hand-writes it for review clarity.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

Verdict = Literal["authentic", "likely-false", "false", "ai-generated", "unverifiable"]
ContentType = Literal["text", "url", "image", "audio", "video"]
ClaimAssessment = Literal["false", "misleading", "unsupported", "out-of-context", "supported"]
CitationStance = Literal["supports", "contradicts", "context"]
RaterRole = Literal["public", "journalist", "expert"]
Role = Literal["public", "journalist", "expert", "admin"]
ApiScope = Literal["submit", "read"]
LocaleCode = Literal["en", "lg", "ach", "nyn", "teo"]
ReviewReason = Literal["community-escalation", "suspended", "user-reports", "low-confidence"]
AuditAction = Literal[
    "verdict.override",
    "verdict.confirm",
    "user.role_change",
    "user.suspend",
    "user.reinstate",
    "ratings.exclude",
    "source.add",
    "source.deactivate",
    "broadcast.send",
    "settings.update",
    "moderation.remove",
    "accreditation.approve",
    "accreditation.reject",
]


class CamelModel(BaseModel):
    """Every response schema subclasses this so `trackingId`/`checkedAt`/`perPage`-style
    camelCase JSON comes out of ordinary snake_case Python fields, matching openapi.yaml."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class PageMeta(CamelModel):
    page: int
    per_page: int
    total: int


class ErrorEnvelopeBody(CamelModel):
    code: str
    message: str
    retry_after: int | None = None


class ErrorEnvelope(CamelModel):
    error: ErrorEnvelopeBody
