"""app/services/provider_health.py (Milestone D6): each AI service's last answer or failure,
as Admin → System health shows it. Redis is the suite's fakeredis (tests/conftest.py)."""

import httpx
import pytest
import respx

from app.core import config
from app.providers.explanation import ChatModel, GroqError, GroqExplanationGenerator
from app.providers.source_verification import EvidenceBundle
from app.realtime import redis_client
from app.services import provider_health


@pytest.fixture(autouse=True)
async def _clean(monkeypatch):
    r = redis_client.get_async_redis()
    for key in await r.keys("zuula:provider:*"):
        await r.delete(key)
    for var in ("GROQ_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    config.get_analysis_settings.cache_clear()
    yield
    monkeypatch.undo()
    config.get_analysis_settings.cache_clear()
    config.get_analysis_settings().pipeline_step_scale = 0.0


def _rows(items):
    return {i.label: (i.value, i.ok, i.note) for i in items}


async def test_only_configured_providers_show_and_unused_ones_are_fine():
    rows = _rows(await provider_health.status_items())
    assert set(rows) == {"Groq", "Gemini"}
    assert rows["Gemini"] == ("Not used yet", True, "backup verdicts")


async def test_a_failure_shows_until_the_next_success():
    await provider_health.record("Groq", ok=True)
    await provider_health.record("Groq", ok=False, error="HTTP 429 (openai/gpt-oss-120b)")
    value, ok, note = _rows(await provider_health.status_items())["Groq"]
    assert (value, ok) == ("Failing", False)
    assert note.startswith("HTTP 429 (openai/gpt-oss-120b) (just now")

    await provider_health.record("Groq", ok=True)
    value, ok, note = _rows(await provider_health.status_items())["Groq"]
    assert (value, ok) == ("Working", True)
    assert note == "Last answer just now; 1 failure today"


@respx.mock
async def test_the_verdict_chain_records_each_model():
    respx.post("https://groq.example/chat/completions").mock(return_value=httpx.Response(503))
    respx.post("https://gemini.example/chat/completions").mock(return_value=httpx.Response(401))
    generator = GroqExplanationGenerator(
        groq_api_key="k",
        groq_api_url="https://groq.example",
        groq_model="gpt-oss",
        fallbacks=(
            ChatModel(name="Gemini", api_url="https://gemini.example", api_key="g", model="flash"),
        ),
    )
    with pytest.raises(GroqError):
        await generator.generate(
            content_type="text", text="x", evidence=EvidenceBundle(sources=[], trusted_domains=[])
        )
    rows = _rows(await provider_health.status_items())
    assert rows["Groq"][:2] == ("Failing", False) and "HTTP 503 (gpt-oss)" in rows["Groq"][2]
    assert rows["Gemini"][:2] == ("Failing", False) and "HTTP 401 (flash)" in rows["Gemini"][2]


async def test_a_redis_outage_never_breaks_a_check(monkeypatch):
    class Down:
        async def hset(self, *args, **kwargs):
            raise ConnectionError("redis is down")

        async def hgetall(self, *args):
            raise ConnectionError("redis is down")

    monkeypatch.setattr(redis_client, "get_async_redis", lambda: Down())
    await provider_health.record("Groq", ok=False, error="HTTP 500")  # no exception
    assert await provider_health.status_items() == []
