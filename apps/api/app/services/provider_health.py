"""How the hosted AI services are doing, for Admin → System health (Milestone D6). On 28 Oct
2026 Sunbird's revoked token and Tavily's used-up quota failed silently for days: checks
still completed, just with thinner reports, and nothing on the admin screen said so.

Every call to Groq, Gemini, OpenRouter, Sunbird, Tavily and Exa records its outcome here:
the time of the last success, the time and reason of the last failure, and a count of
today's failures. Kept in Redis so the API and a Celery worker see the same numbers.
Recording is best effort: a Redis hiccup must never fail a fact-check.
"""

import logging
import time
from datetime import UTC, datetime

from app.core.config import get_analysis_settings, get_language_settings
from app.realtime import redis_client
from app.schemas.admin import SystemHealthItem

logger = logging.getLogger("zuula.services.provider_health")

# Shown in this order; a provider appears only when its key is set.
PROVIDERS = (
    "Groq",
    "Gemini",
    "OpenRouter",
    "Sunbird",
    "Tavily",
    "Exa",
    "Gemini embeddings",
    "Hugging Face",
)
_WHAT = {
    "Groq": "verdicts and images",
    "Gemini": "backup verdicts",
    "OpenRouter": "second backup",
    "Sunbird": "Ugandan languages",
    "Tavily": "web search",
    "Exa": "backup search",
    "Gemini embeddings": "duplicate search",
    "Hugging Face": "duplicate search",
}
_KEY = "zuula:provider:{}"
_FAILS = "zuula:provider:{}:fails:{}"


async def record(provider: str, *, ok: bool, error: str = "") -> None:
    """Note one call's outcome. `error` is a short reason (an HTTP status, an exception
    name); it's shown to admins, so callers never put request text or keys in it."""
    now = time.time()
    try:
        r = redis_client.get_async_redis()
        if ok:
            await r.hset(_KEY.format(provider), mapping={"ok_at": now})
            return
        await r.hset(_KEY.format(provider), mapping={"error_at": now, "error": error[:160]})
        fails = _FAILS.format(provider, datetime.now(UTC).date().isoformat())
        await r.incr(fails)
        await r.expire(fails, 2 * 86400)
    except Exception:  # noqa: BLE001 — health bookkeeping must never fail a check
        logger.debug("Couldn't record %s's health", provider, exc_info=True)


def _configured() -> list[str]:
    analysis, language = get_analysis_settings(), get_language_settings()
    keys = {
        "Groq": analysis.groq_api_key,
        "Gemini": analysis.gemini_api_key,
        "OpenRouter": analysis.openrouter_api_key,
        "Sunbird": language.sunbird_api_key,
        "Tavily": analysis.tavily_api_key,
        "Exa": analysis.exa_api_key,
        "Gemini embeddings": analysis.gemini_api_key
        if analysis.embedding_provider.strip().lower() == "gemini"
        else "",
        "Hugging Face": analysis.hf_token
        if analysis.embedding_provider.strip().lower() == "huggingface"
        else "",
    }
    return [p for p in PROVIDERS if keys[p]]


def _ago(seconds: float) -> str:
    if seconds < 90:
        return "just now"
    if seconds < 90 * 60:
        return f"{round(seconds / 60)} min ago"
    if seconds < 36 * 3600:
        return f"{round(seconds / 3600)} h ago"
    return f"{round(seconds / 86400)} days ago"


async def status_items() -> list[SystemHealthItem]:
    """One System health row per configured provider. Failing means the most recent call
    failed; a backup that has never been needed shows as unused, which is fine."""
    now = time.time()
    today = datetime.now(UTC).date().isoformat()
    try:
        r = redis_client.get_async_redis()
        items = []
        for provider in _configured():
            state = await r.hgetall(_KEY.format(provider))
            fails = int(await r.get(_FAILS.format(provider, today)) or 0)
            ok_at = float(state.get("ok_at") or 0)
            error_at = float(state.get("error_at") or 0)
            failing = error_at > ok_at
            if failing:
                value, note = "Failing", f"{state.get('error', 'Error')} ({_ago(now - error_at)})"
            elif ok_at:
                value, note = "Working", f"Last answer {_ago(now - ok_at)}"
            else:
                value, note = "Not used yet", _WHAT[provider]
            if fails and not failing:
                note += f"; {fails} failure{'s' if fails != 1 else ''} today"
            items.append(SystemHealthItem(label=provider, value=value, ok=not failing, note=note))
        return items
    except Exception:  # noqa: BLE001 — Redis down: the database rows still show
        logger.warning("Couldn't read AI provider health", exc_info=True)
        return []
