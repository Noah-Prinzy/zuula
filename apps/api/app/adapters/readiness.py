"""Which adapters run for real, and the production guard (ADR 0002 §7).

Every adapter's `get_*()` factory uses the real implementation when that adapter's settings
are filled in and the logging stub otherwise, which keeps local dev and the tests free of
external services. In production a stub would silently drop SMS codes, skip malware scans or
accept any captcha, so `ZUULA_ENV=production` with anything missing stops the API and the
worker at startup instead (`assert_production_ready()`), naming every missing variable.

A deployment that knowingly runs without some integrations (a demo, or a launch before the
WhatsApp number exists) lists them in `ZUULA_ALLOW_STUB_ADAPTERS`, e.g. `whatsapp,telegram`.
Those start with a warning instead. The stubs that would be unsafe in production are
switched off rather than used: sign-in with an unconfigured OAuth provider is unavailable,
and an unconfigured WhatsApp/Telegram webhook refuses every call. `ZUULA_SECRET_KEY` can
never be left at its development default.
"""

import logging

from app.core.config import AdaptersSettings, Settings, get_adapters_settings, get_settings

logger = logging.getLogger("zuula.adapters")

_DEV_SECRET_KEY = "change-me-dev-only"

# Adapter id (as ZUULA_ALLOW_STUB_ADAPTERS spells it) → (name, the .env variables it needs,
# all of them, to run for real).
ADAPTERS: dict[str, tuple[str, tuple[str, ...]]] = {
    "google": ("Google sign-in", ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET")),
    "facebook": (
        "Facebook sign-in",
        ("FACEBOOK_OAUTH_CLIENT_ID", "FACEBOOK_OAUTH_CLIENT_SECRET"),
    ),
    "sms": ("SMS (Africa's Talking)", ("AFRICASTALKING_USERNAME", "AFRICASTALKING_API_KEY")),
    # Plus a way to send: BREVO_API_KEY (HTTPS, works where SMTP ports are blocked, as on
    # Render's free tier) or EMAIL_SMTP_HOST. See _missing().
    "email": ("Email (Brevo API or SMTP)", ("EMAIL_FROM",)),
    "turnstile": ("Captcha (Turnstile)", ("TURNSTILE_SECRET_KEY",)),
    "clamav": ("Malware scanning (ClamAV)", ("CLAMAV_HOST",)),
    "s3": ("Media storage (S3)", ("S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY")),
    "whatsapp": (
        "WhatsApp",
        (
            "WHATSAPP_VERIFY_TOKEN",
            "WHATSAPP_ACCESS_TOKEN",
            "WHATSAPP_PHONE_NUMBER_ID",
            "WHATSAPP_APP_SECRET",
        ),
    ),
    "telegram": ("Telegram", ("TELEGRAM_BOT_TOKEN", "TELEGRAM_WEBHOOK_SECRET")),
}


def configured(adapter: str, settings: AdaptersSettings | None = None) -> bool:
    settings = settings or get_adapters_settings()
    if adapter == "email" and not (settings.brevo_api_key or settings.email_smtp_host):
        return False
    return all(getattr(settings, var.lower()) for var in ADAPTERS[adapter][1])


def is_production(settings: Settings | None = None) -> bool:
    return (settings or get_settings()).env == "production"


def allowed_stubs(settings: Settings) -> set[str]:
    listed = {a.strip().lower() for a in settings.allow_stub_adapters.split(",") if a.strip()}
    unknown = listed - set(ADAPTERS)
    if unknown:
        raise RuntimeError(
            f"ZUULA_ALLOW_STUB_ADAPTERS names unknown adapters: {', '.join(sorted(unknown))}. "
            f"Known: {', '.join(ADAPTERS)}."
        )
    return listed


def _missing(adapter: str, adapters: AdaptersSettings) -> list[str]:
    missing = [var for var in ADAPTERS[adapter][1] if not getattr(adapters, var.lower())]
    # The sandbox username only reaches Africa's Talking's simulator: no SMS is delivered.
    if adapter == "sms" and adapters.africastalking_username == "sandbox":
        missing.append("AFRICASTALKING_USERNAME (not 'sandbox')")
    if adapter == "email" and not (adapters.brevo_api_key or adapters.email_smtp_host):
        missing.append("BREVO_API_KEY or EMAIL_SMTP_HOST")
    return missing


def missing_for_production(settings: Settings, adapters: AdaptersSettings) -> list[str]:
    allowed = allowed_stubs(settings)
    missing = [
        var for adapter in ADAPTERS if adapter not in allowed for var in _missing(adapter, adapters)
    ]
    # Signs one-time codes and the OAuth state cookie; no exception for this one.
    if settings.secret_key in ("", _DEV_SECRET_KEY):
        missing.append("ZUULA_SECRET_KEY (not the development default)")
    return missing


def assert_production_ready(
    settings: Settings | None = None, adapters: AdaptersSettings | None = None
) -> None:
    settings = settings or get_settings()
    if not is_production(settings):
        return
    adapters = adapters or get_adapters_settings()
    missing = missing_for_production(settings, adapters)
    if missing:
        raise RuntimeError(
            "ZUULA_ENV=production, but these settings are missing, so the API would fall back "
            "to stub adapters: "
            + ", ".join(missing)
            + ". Set them, or list the adapter in ZUULA_ALLOW_STUB_ADAPTERS to run without it."
        )
    stubbed = [ADAPTERS[a][0] for a in ADAPTERS if _missing(a, adapters)]
    if stubbed:
        logger.warning(
            "Running in production WITHOUT: %s (ZUULA_ALLOW_STUB_ADAPTERS). Sign-in with an "
            "unconfigured provider and unconfigured chat webhooks are switched off.",
            ", ".join(stubbed),
        )
