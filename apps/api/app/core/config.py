from functools import lru_cache
from typing import Literal

from pydantic import Field
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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://zuula:zuula@localhost:5432/zuula"
    database_pool_size: int = 5
    database_echo: bool = False


class SupabaseSettings(BaseSettings):
    """Supabase Auth (Phase 1.2, see app/core/supabase_auth.py). The API verifies Supabase
    access tokens against the project's JWKS, or SUPABASE_JWT_SECRET for HS256 tokens; the web
    app uses the publishable key."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: str = ""
    # Legacy shared secret; only needed while the project still signs tokens with HS256.
    supabase_jwt_secret: str = ""
    # "legacy" = the zuula_session cookie (security.py); "supabase" = Supabase access tokens.
    auth_provider: str = Field("legacy", validation_alias="ZUULA_AUTH_PROVIDER")

    @property
    def issuer(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1"

    @property
    def jwks_url(self) -> str:
        return f"{self.issuer}/.well-known/jwks.json"

    @property
    def is_supabase_enabled(self) -> bool:
        return self.auth_provider == "supabase" and bool(self.supabase_url)


class CelerySettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    # Where background jobs run (app/worker/dispatch.py): "celery", a separate worker process,
    # or "inline", tasks inside the API's own event loop, for a single free-tier instance
    # with no worker (Render free). Inline jobs in flight are lost if the process restarts.
    job_runner: Literal["celery", "inline"] = "celery"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    # Shared by app/realtime/ too — pub/sub for SSE lives on the same Redis, a different DB
    # index from the Celery broker/backend so a `FLUSHDB` on one doesn't take out the other.
    redis_url: str = "redis://localhost:6379/2"


class AnalysisSettings(BaseSettings):
    """Sending submissions to a hosted LLM outside Uganda is an open §10.1 data-protection
    question (see the P2 brief and docs/zuula_state.md, ADR 0001), so the provider and
    its region must be switchable rather than hardcoded. P2 shipped only `stub`; P4 adds
    `groq` (a free-tier hosted model on Groq, chosen over Claude purely on cost — see the P4
    brief) behind the same app.providers.analysis.AnalysisProvider interface. Groq's
    inference is also hosted outside Uganda, so §10.1 is still open either way; this field
    doesn't resolve it, it just keeps the choice a switch rather than a hardcoded default."""

    model_config = SettingsConfigDict(extra="ignore")

    # Empty (the default) = Groq when GROQ_API_KEY is set, the stub otherwise — same
    # real-when-configured rule as LanguageSettings.language_provider; `stub`/`groq` pick one
    # explicitly.
    analysis_provider: str = ""
    analysis_provider_region: str = ""
    # Pads each pipeline step that finishes early up to STEP_SECONDS × this factor (the
    # display times in apps/web/lib/analysis.ts). 0 (production, tests): a check takes as long
    # as its real work. 1.0 gives local dev with stub providers the demo's paced progress.
    pipeline_step_scale: float = 0.0

    # `groq` provider (app/providers/analysis.py's GroqAnalysisProvider): one chat completion
    # per claim (Groq's free tier) over the claim text and Tavily's search results — no agent
    # loop, no Claude/Anthropic calls anywhere in this engine.
    #
    # The P4 brief specified Llama 3.3 70B; Groq has since fully retired every Llama text
    # model from its catalog (GET /v1/models no longer lists one at all, confirmed while
    # building the eval harness in scripts/run_eval.py — every call 404s with
    # "model_not_found" otherwise). openai/gpt-oss-120b is Groq's current free-tier model
    # closest in size/capability and was confirmed to support the same JSON response_format
    # this provider relies on.
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    # app/providers/transcription.py's GroqWhisperProvider — same key, Groq's hosted Whisper
    # (free tier, 2,000 requests/day).
    groq_whisper_model: str = "whisper-large-v3-turbo"
    groq_api_url: str = "https://api.groq.com/openai/v1"
    # Fallbacks for the verdict when Groq fails (Milestone D3), tried in this order, each only
    # when its key is set. Both speak the same OpenAI-style chat API as Groq. Free keys:
    # Google AI Studio (Gemini) and openrouter.ai (models ending in `:free`). Each *_MODEL is
    # a comma-separated list tried in order: free models get retired or overloaded often
    # (29 Oct 2026: gemini-2.5-flash closed to new keys, gemini-flash-latest hanging past
    # 90 s, gemma-4-31b:free answering 502), so one name alone isn't enough.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.1-flash-lite,gemini-flash-lite-latest"
    gemini_api_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    openrouter_api_key: str = ""
    openrouter_model: str = "nvidia/nemotron-3.5-super-vl:free,google/gemma-4-31b-it:free"
    openrouter_api_url: str = "https://openrouter.ai/api/v1"
    # TRANSCRIPTION_PROVIDER: independent of ANALYSIS_PROVIDER so either can be exercised on
    # its own. Same empty/`stub`/`groq` convention as LANGUAGE_PROVIDER.
    transcription_provider: str = ""
    # app/providers/tavily.py — one web search per claim (free tier, 1,000 searches/month).
    tavily_api_key: str = ""
    tavily_api_url: str = "https://api.tavily.com"

    # app/providers/vector_db.py: where the dedupe check's nearest-neighbor lookup runs.
    # `pgvector` (default) matches the live demo path exactly — queries
    # `fact_check_reports.embedding` directly, no extra infrastructure. `pinecone` is the
    # additive alternative satisfying §4.2/§4.1 Layer 4's named vector-DB choice.
    vector_db_provider: str = "pgvector"
    pinecone_api_key: str = ""
    pinecone_host: str = ""

    # app/providers/embedding.py: local sentence-embedding model for the dedupe check and the
    # local-evidence retrieval step (no API key, CPU-only). Defaults to `stub` — same
    # real-when-configured spirit as the other providers, but gated on an explicit opt-in
    # rather than a credential, since there's no key to gate on and the real model is a
    # download the test suite must never trigger. `ANALYSIS_PROVIDER=groq` in production
    # should set this to `sentence-transformers`.
    embedding_provider: str = "stub"
    # paraphrase-multilingual-MiniLM-L12-v2, not the original all-MiniLM-L6-v2: same
    # sentence-transformers family and the same 384-dim output (no migration needed — see
    # migrations/versions/0004_embedding_dimensions.py), but trained across 50+ languages
    # rather than English-only. Uganda's submissions aren't all English (Luganda, Acholi,
    # Swahili, ...); the English-only model couldn't match a non-English resubmission of an
    # already-checked claim to its existing report, nor to a related one in the local-evidence
    # corpus below. See docs/zuula_state.md, ADR 0004.
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    # Cosine distance (1 - cosine similarity) below which a new claim is treated as a
    # near-duplicate of an existing report and reused instead of re-run through Tavily+Groq.
    # 0.08 is roughly 92% cosine similarity — tight enough that two different claims about the
    # same event shouldn't collide, loose enough to catch the reworded/retranslated copies of
    # the same viral claim that make repeats worth catching. Picked by inspection, not a tuned
    # threshold; revisit once real traffic exists.
    dedupe_max_cosine_distance: float = 0.08
    # Looser than dedupe_max_cosine_distance: a match in this band isn't the same claim (not
    # reused outright) but is close enough to be useful grounding — a previously-verified
    # report on the same or a closely related claim, surfaced to the Explanation Generator as
    # an always-trusted citation alongside the live Tavily search (app/providers/analysis.py's
    # GroqAnalysisProvider._augment_with_local_evidence). This is the local half of the
    # engine's retrieval: our own verified corpus, not the open web. Same "picked by
    # inspection" caveat as dedupe_max_cosine_distance.
    local_evidence_max_cosine_distance: float = 0.3
    # How many local-corpus matches (within local_evidence_max_cosine_distance) to surface per
    # claim at most.
    local_evidence_limit: int = 3

    # app/providers/ai_text_detector.py: in-process RoBERTa AI-generated-text classifier
    # (CPU, no hosted endpoint). Same stub-by-default reasoning as embedding_provider.
    ai_text_detector_provider: str = "stub"
    ai_text_detector_model: str = "openai-community/roberta-base-openai-detector"

    # app/providers/metadata_integrity.py: EXIF-metadata + content-hash tampering check for
    # image submissions (§5.3 "Metadata Tampering"). No model, no download — defaults to
    # `stub` anyway, same reasoning as the other signals: nobody's reviewed the heuristic on
    # real traffic yet, so it shouldn't start flagging submissions silently.
    metadata_tampering_provider: str = "stub"

    # app/providers/deepfake_detector.py: a pretrained (not fine-tuned) image classifier's
    # AI-generated/synthetic-image signal — the achievable slice of §5.3's deepfake detection
    # row given no labelled corpus or GPU budget for a real CNNDetection/FaceForensics++-style
    # detector. Same stub-by-default reasoning as ai_text_detector_provider.
    deepfake_detector_provider: str = "stub"
    deepfake_detector_model: str = "umm-maybe/AI-image-detector"


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
    # Brevo's HTTPS API; preferred over SMTP when set (SMTP ports are blocked on some hosts).
    brevo_api_key: str = ""
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


@lru_cache
def get_supabase_settings() -> SupabaseSettings:
    return SupabaseSettings()
