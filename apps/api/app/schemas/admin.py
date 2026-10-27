from datetime import date, datetime
from typing import Literal

from app.schemas.common import AuditAction, CamelModel, Role, Verdict

KpiUnit = Literal["%", "s", "h", "", "/5"]
SourceType = Literal["media", "government", "fact-checker", "international", "academic"]


class Kpi(CamelModel):
    id: str
    label: str
    value: float
    unit: KpiUnit
    target: float
    direction: str  # min | max
    note: str


class DailyCheckPoint(CamelModel):
    date: date
    checks: int


class VerdictCount(CamelModel):
    verdict: Verdict
    count: int


class SystemHealthItem(CamelModel):
    label: str
    value: str
    ok: bool
    note: str


class AdminOverview(CamelModel):
    kpis: list[Kpi]
    daily_checks: list[DailyCheckPoint]
    verdict_mix: list[VerdictCount]
    system_health: list[SystemHealthItem]


class AdminUser(CamelModel):
    id: str
    name: str
    email: str
    role: Role
    status: str  # active | suspended | pending
    joined: date
    last_active: date
    ratings: int


class ContentReport(CamelModel):
    id: str
    report_id: str
    title: str
    reason: str
    reporters: int
    sample: str
    reported_at: datetime


class ManipulationSignal(CamelModel):
    id: str
    report_id: str
    title: str
    pattern: str
    accounts: int
    window: str
    direction: str  # accurate | inaccurate
    confidence: float


class TrustedSource(CamelModel):
    id: str
    name: str
    domain: str
    type: SourceType
    languages: list[str]
    tier: int
    active: bool
    last_crawled: datetime
    crawl_ok: bool


class TrustedSourceInput(CamelModel):
    name: str
    domain: str
    type: SourceType
    languages: list[str]
    tier: int
    active: bool = True


class Broadcast(CamelModel):
    id: str
    title: str
    message: str
    severity: str  # high | critical
    audience: str
    channels: list[str]
    sent_at: datetime
    sent_by: str
    reach: int
    opened: int


class MonthlyReport(CamelModel):
    month: str  # YYYY-MM
    checks: int
    false_share: float
    ai_generated: int
    top_categories: list[str]
    avg_delivery: float


class AuditEntry(CamelModel):
    id: str
    at: datetime
    actor: str
    actor_role: Role
    action: AuditAction
    target: str
    detail: str
    ip: str


class Thresholds(CamelModel):
    verified_min: int
    questioned_min: int
    questioned_max: int
    questioned_ratings: int
    escalated_max: int
    escalated_ratings: int
    suspended_max: int
    suspended_ratings: int


class Weights(CamelModel):
    """§9.1. The spec is silent on admins; the app uses 1x (open question for the supervisor)."""

    public: int
    journalist: int
    expert: int


class Retraining(CamelModel):
    cadence: str  # weekly | monthly
    min_ccs: int


class PlatformSettings(CamelModel):
    thresholds: Thresholds
    weights: Weights
    sla_hours: int
    api_rate_limit: int
    retraining: Retraining


AccreditationRole = Literal["journalist", "expert"]


class AccreditationApplicant(CamelModel):
    id: str
    name: str
    email: str  # or their phone, for a phone-only account (same as AdminUser.email)
    role: Role
    status: str  # active | suspended | pending
    district: str | None = None
    joined: date


class AccreditationDocument(CamelModel):
    index: int
    url: str  # signed, short-lived path on this API; opens without a session
    expires_at: datetime


class AccreditationApplication(CamelModel):
    id: str
    status: str  # pending | approved | rejected
    requested_role: AccreditationRole
    organisation: str | None = None
    press_card_number: str | None = None
    submitted_at: datetime
    reviewed_at: datetime | None = None
    reviewer: str | None = None
    note: str | None = None
    document_count: int
    applicant: AccreditationApplicant


class AccreditationApplicationDetail(AccreditationApplication):
    documents: list[AccreditationDocument]
