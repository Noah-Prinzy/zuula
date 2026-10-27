from datetime import datetime

from app.schemas.common import ApiScope, CamelModel, LocaleCode, Role


class UserProfile(CamelModel):
    id: str
    name: str
    email: str
    phone: str | None = None
    role: Role
    preferred_language: LocaleCode | None = None
    district: str | None = None
    two_factor_enabled: bool = False
    created_at: datetime | None = None


class Session(CamelModel):
    user: UserProfile


class TwoFactorChallenge(CamelModel):
    challenge_id: str
    masked_identifier: str


class DeviceSession(CamelModel):
    id: str
    device: str
    location: str
    last_active: str
    current: bool


class AccreditationStatus(CamelModel):
    status: str  # none | pending | approved | rejected
    role: str | None = None  # the role applied for: journalist | expert
    organisation: str | None = None
    submitted_at: datetime | None = None
    reviewed_at: datetime | None = None
    note: str | None = None


class ApiKey(CamelModel):
    id: str
    name: str
    prefix: str
    scopes: list[ApiScope]
    created_at: str
    last_used_at: datetime | None = None


class ApiKeyCreated(ApiKey):
    secret: str


def dump_api_key(model: ApiKey) -> dict:
    """openapi.yaml requires `lastUsedAt` (oneOf string/null) — unlike most optional fields in
    this contract, a never-used key must still show the key as explicit `null`, not omit it."""
    data = model.model_dump(by_alias=True, mode="json", exclude_none=True)
    data.setdefault("lastUsedAt", None)
    return data
