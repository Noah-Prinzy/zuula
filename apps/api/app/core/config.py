from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.rules import PARTNER_RATE_LIMIT_PER_HOUR


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ZUULA_", env_file=".env", extra="ignore")

    env: str = "development"
    # Production only: adapters it may run without (comma-separated ids, e.g.
    # "whatsapp,telegram"). See app/adapters/readiness.py.
    allow_stub_adapters: str = ""
    debug: bool = True
    secret_key: str = "change-me-dev-only"
    session_cookie_name: str = "zuula_session"
    # ADR 0002 §5 / decision 9: the API is api.zuula.ug and the web app zuula.ug, so production
    # sets ZUULA_SESSION_COOKIE_DOMAIN=zuula.ug. Empty = host-only (local dev).
    session_cookie_domain: str = ""
    session_cookie_secure: bool = True
    cors_origins: str = "http://localhost:3000"
    # Where the web app lives (zuula.ug in production): OAuth callbacks redirect the browser
    # back here, since the API is on its own host (api.zuula.ug).
    web_app_url: str = "http://localhost:3000"

    # Independently overridable via ZUULA_PARTNER_RATE_LIMIT_PER_HOUR — see
    # app/core/rules.py's PARTNER_RATE_LIMIT_PER_HOUR for why this defaults to it rather
    # than hardcoding its own copy of the same number.
    partner_rate_limit_per_hour: int = PARTNER_RATE_LIMIT_PER_HOUR

    # How long one GET /notifications/stream connection stays open before the server closes
    # it; EventSource reconnects on its own and resumes from Last-Event-ID. Bounded so proxies
    # and dead clients can't pin connections forever. Tests set 0 (replay, then close).
    notification_stream_seconds: int = 300

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


class DatabaseSettings(BaseSettings):
    """PostgreSQL (+ pgvector). Same no-prefix convention as the settings classes below —
    field names match .env.example's var names. The URL must use the asyncpg driver
    (`postgresql+asyncpg://`); the worker runs its DB work through the same async engine."""

    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = "postgresql+asyncpg://zuula:zuula@localhost:5432/zuula"
    database_pool_size: int = 5
    database_echo: bool = False


class CelerySettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    # Shared by app/realtime/ too — pub/sub for SSE lives on the same Redis, a different DB
    # index from the Celery broker/backend so a `FLUSHDB` on one doesn't take out the other.
    redis_url: str = "redis://localhost:6379/2"


class AnalysisSettings(BaseSettings):
    """Sending submissions to a hosted LLM outside Uganda is an open §10.1 data-protection
    question (see the P2 brief and docs/adr/0001-api-architecture.md), so the provider and
    its region must be switchable rather than hardcoded. P2 shipped only `stub`; P4 adds
    `groq` (Groq's free-tier hosted Llama 3.3 70B, chosen over Claude purely on cost — see
    the P4 brief) behind the same app.providers.analysis.AnalysisProvider interface. Groq's
    inference is also hosted outside Uganda, so §10.1 is still open either way; this field
    doesn't resolve it, it just keeps the choice a switch rather than a hardcoded default."""

    model_config = SettingsConfigDict(extra="ignore")

    # Empty (the default) = Groq when GROQ_API_KEY is set, the stub otherwise — same
    # real-when-configured rule as LanguageSettings.language_provider; `stub`/`groq` pick one
    # explicitly.
    analysis_provider: str = ""
    analysis_provider_region: str = ""
    # Real step durations (app/worker/pipeline.py's STEP_SECONDS, matching
    # apps/web/lib/analysis.ts) are scaled by this factor — 1.0 for a realistic demo feel,
    # near-0 so pipeline tests don't spend ~10 real seconds per text submission.
    pipeline_step_scale: float = 1.0

    # `groq` provider (app/providers/analysis.py's GroqAnalysisProvider): one chat completion
    # per claim (Llama 3.3 70B, Groq's free tier) over the claim text and Tavily's search
    # results — no agent loop, no Claude/Anthropic calls anywhere in this engine.
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    # app/providers/transcription.py's GroqWhisperProvider — same key, Groq's hosted Whisper
    # (free tier, 2,000 requests/day).
    groq_whisper_model: str = "whisper-large-v3-turbo"
    groq_api_url: str = "https://api.groq.com/openai/v1"
    # TRANSCRIPTION_PROVIDER: independent of ANALYSIS_PROVIDER so either can be exercised on
    # its own. Same empty/`stub`/`groq` convention as LANGUAGE_PROVIDER.
    transcription_provider: str = ""
    # app/providers/tavily.py — one web search per claim (free tier, 1,000 searches/month).
    tavily_api_key: str = ""
    tavily_api_url: str = "https://api.tavily.com"

    # app/providers/embedding.py: local sentence-embedding model for the dedupe check
    # (no API key, CPU-only). Defaults to `stub` — same real-when-configured spirit as the
    # other providers, but gated on an explicit opt-in rather than a credential, since there's
    # no key to gate on and the real model is a ~90MB download the test suite must never
    # trigger. `ANALYSIS_PROVIDER=groq` in production should set this to
    # `sentence-transformers`.
    embedding_provider: str = "stub"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    # Cosine distance (1 - cosine similarity) below which a new claim is treated as a
    # near-duplicate of an existing report and reused instead of re-run through Tavily+Groq.
    # 0.08 is roughly 92% cosine similarity on all-MiniLM-L6-v2 — tight enough that two
    # different claims about the same event shouldn't collide, loose enough to catch the
    # reworded/retranslated copies of the same viral claim that make repeats worth catching.
    # Picked by inspection, not a tuned threshold; revisit once real traffic exists.
    dedupe_max_cosine_distance: float = 0.08

    # app/providers/ai_text_detector.py: in-process RoBERTa AI-generated-text classifier
    # (CPU, no hosted endpoint). Same stub-by-default reasoning as embedding_provider.
    ai_text_detector_provider: str = "stub"
    ai_text_detector_model: str = "openai-community/roberta-base-openai-detector"

    # Deepfake detection (image/video ai_signals) is explicitly out of scope for this engine:
    # Reality Defender's free tier (50/month) doesn't cover it affordably, and the owner opted
    # to skip it for v1 rather than half-build it. See AnalysisResult/ai_signals usage in
    # app/providers/analysis.py.


class LanguageSettings(BaseSettings):
    """Language detection and translation (app/providers/language.py, ADR 0003). Same
    no-prefix convention as AnalysisSettings. LANGUAGE_PROVIDER picks the implementation:
    `sunbird`, `stub`, or empty (the default) for Sunbird when SUNBIRD_API_KEY is set and the
    stub otherwise. Sunbird is a Ugandan organisation; whether that settles §10.1 data
    protection for sending submissions to it is still to be confirmed (ADR 0003)."""

    model_config = SettingsConfigDict(extra="ignore")

    language_provider: str = ""
    sunbird_api_url: str = "https://api.sunbird.ai"
    sunbird_api_key: str = ""


class AdaptersSettings(BaseSettings):
    """Config for every integration adapter (app/adapters/**). Each adapter uses its real
    implementation when its credentials are set and the logging stub otherwise; in
    production, missing credentials stop startup instead (app/adapters/readiness.py). Field
    names match .env.example's var names, no ZUULA_ prefix — same convention as
    CelerySettings/AnalysisSettings."""

    model_config = SettingsConfigDict(extra="ignore")

    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    facebook_oauth_client_id: str = ""
    facebook_oauth_client_secret: str = ""

    africastalking_username: str = "sandbox"
    africastalking_api_key: str = ""

    turnstile_site_key: str = ""
    turnstile_secret_key: str = ""

    # Empty = no scanner (the stub reports every file clean). docker-compose.yml sets it.
    clamav_host: str = ""
    clamav_port: int = 3310

    s3_endpoint_url: str = ""
    s3_bucket: str = "zuula-media-dev"
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_region: str = "us-east-1"

    email_from: str = "hello@zuula.ug"
    email_smtp_host: str = ""
    email_smtp_port: int = 587
    email_smtp_user: str = ""
    email_smtp_password: str = ""

    # FR-SUBMIT-04: WhatsApp/Telegram messages create submissions — see app/webhooks/.
    whatsapp_verify_token: str = ""
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    # Signs every inbound webhook call (X-Hub-Signature-256): the Meta app's App Secret.
    whatsapp_app_secret: str = ""
    telegram_bot_token: str = ""
    # Sent back on every inbound call (X-Telegram-Bot-Api-Secret-Token): the `secret_token`
    # you pass to setWebhook.
    telegram_webhook_secret: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_database_settings() -> DatabaseSettings:
    return DatabaseSettings()


@lru_cache
def get_celery_settings() -> CelerySettings:
    return CelerySettings()


@lru_cache
def get_analysis_settings() -> AnalysisSettings:
    return AnalysisSettings()


@lru_cache
def get_language_settings() -> LanguageSettings:
    return LanguageSettings()


@lru_cache
def get_adapters_settings() -> AdaptersSettings:
    return AdaptersSettings()
