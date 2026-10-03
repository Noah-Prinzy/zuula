"""GroqAnalysisProvider: the pgvector dedupe check and the Tavily+Groq verdict path, both
against respx mocks (for the hosted calls) and the real test database (for dedupe). Nothing
calls a real service."""

import json
from datetime import UTC, datetime

import httpx
import pytest
import respx

from app.core import config
from app.db import models as m
from app.providers.ai_text_detector import StubAiTextDetector
from app.providers.analysis import GroqAnalysisProvider, GroqError, get_analysis_provider
from app.providers.embedding import StubEmbeddingProvider

GROQ_URL = "https://groq.example"
TAVILY_URL = "https://tavily.example"
CHAT = f"{GROQ_URL}/chat/completions"
SEARCH = f"{TAVILY_URL}/search"


def _provider(**overrides):
    kwargs = {
        "groq_api_key": "groq-key",
        "groq_api_url": GROQ_URL,
        "groq_model": "llama-3.3-70b-versatile",
        "tavily_api_key": "tavily-key",
        "tavily_api_url": TAVILY_URL,
        "embedder": StubEmbeddingProvider(),
        "ai_text_detector": StubAiTextDetector(),
        "dedupe_max_cosine_distance": 0.08,
    }
    kwargs.update(overrides)
    return GroqAnalysisProvider(**kwargs)


def _verdict_response(**fields) -> httpx.Response:
    body = {
        "verdict": "false",
        "confidence": 85,
        "title": "A claim",
        "summary": "It's false.",
        "category": "Politics",
        "whatIsFalse": ["The core claim is false."],
        "whatIsTrue": [],
        "claims": [],
        "citationStances": [],
    }
    body.update(fields)
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(body)}}]})


async def _existing_report(db, *, text: str, tracking_id: str, report_id: str) -> m.FactCheckReport:
    db.add(m.Submission(tracking_id=tracking_id, type="text", status="completed"))
    await db.flush()
    report = m.FactCheckReport(
        id=report_id,
        tracking_id=tracking_id,
        title="An existing fact-check",
        content_type="text",
        language="English",
        verdict="false",
        confidence=88,
        summary="Already debunked.",
        category="Politics",
        checked_at=datetime.now(UTC),
        processing_seconds=1.0,
        embedding=StubEmbeddingProvider().embed(text),
    )
    db.add(report)
    await db.flush()
    return report


@respx.mock
async def test_a_near_duplicate_claim_reuses_the_existing_report_without_calling_out(db):
    text = "Free unlimited internet for every Ugandan starting January 2027."
    existing = await _existing_report(
        db, text=text, tracking_id="ZL-ABCD-EF", report_id="fc-2026-9001"
    )

    result = await _provider().analyze(db=db, content_type="text", text=text, language="en")

    # respx.mock with no routes registered raises on any HTTP call, so no exception here is
    # itself the proof that neither Tavily nor Groq was called.
    assert (result.title, result.verdict, result.confidence) == (
        existing.title,
        "false",
        88,
    )
    assert result.embedding == StubEmbeddingProvider().embed(text)


@respx.mock
async def test_an_unrelated_claim_is_not_reused_and_goes_through_groq(db):
    await _existing_report(
        db,
        text="Free unlimited internet for every Ugandan starting January 2027.",
        tracking_id="ZL-ABCE-EF",
        report_id="fc-2026-9002",
    )
    respx.post(SEARCH).mock(return_value=httpx.Response(200, json={"results": []}))
    respx.post(CHAT).mock(
        return_value=_verdict_response(verdict="unverifiable", title="A new hospital", confidence=40)
    )
    result = await _provider().analyze(
        db=db,
        content_type="text",
        text="The president opened a new hospital in Mbale today.",
        language="en",
    )
    assert result.verdict == "unverifiable" and result.title == "A new hospital"


@respx.mock
async def test_citations_and_claims_are_built_from_the_cited_sources(db):
    respx.post(SEARCH).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"title": "Source A", "url": "https://a.example", "content": "Evidence A"},
                    {"title": "Source B", "url": "https://b.example", "content": "Evidence B"},
                ]
            },
        )
    )
    respx.post(CHAT).mock(
        return_value=_verdict_response(
            claims=[
                {
                    "text": "a new hospital",
                    "assessment": "false",
                    "reason": "No such hospital exists.",
                    "sourceIndexes": [1],
                }
            ],
            citationStances=[{"index": 1, "stance": "contradicts"}],
        )
    )
    text = "The president opened a new hospital in Mbale today."
    result = await _provider().analyze(db=db, content_type="text", text=text, language="en")

    assert [c.url for c in result.citations] == ["https://b.example"]
    assert result.citations[0].stance == "contradicts"
    assert len(result.claims) == 1
    claim = result.claims[0]
    assert claim.citation_ids == [result.citations[0].id]
    assert text[claim.start : claim.end] == "a new hospital"


@respx.mock
async def test_a_tavily_failure_still_produces_a_verdict(db):
    respx.post(SEARCH).mock(return_value=httpx.Response(500))
    respx.post(CHAT).mock(return_value=_verdict_response())
    result = await _provider().analyze(db=db, content_type="text", text="Some claim.", language="en")
    assert result.verdict == "false"


@respx.mock
async def test_a_groq_http_error_raises(db):
    respx.post(SEARCH).mock(return_value=httpx.Response(200, json={"results": []}))
    respx.post(CHAT).mock(return_value=httpx.Response(500))
    with pytest.raises(GroqError):
        await _provider().analyze(db=db, content_type="text", text="Some claim.", language="en")


@respx.mock
async def test_malformed_groq_json_raises(db):
    respx.post(SEARCH).mock(return_value=httpx.Response(200, json={"results": []}))
    respx.post(CHAT).mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "not valid json"}}]}
        )
    )
    with pytest.raises(GroqError):
        await _provider().analyze(db=db, content_type="text", text="Some claim.", language="en")


@respx.mock
async def test_the_ai_text_detector_signal_is_appended_for_text_only(db):
    respx.post(SEARCH).mock(return_value=httpx.Response(200, json={"results": []}))
    respx.post(CHAT).mock(return_value=_verdict_response())

    class FixedSignal:
        def detect(self, text):
            from app.schemas.fact_check import AISignal

            return AISignal(
                id="x", label="AI-generated text", description="d", score=0.9, threshold=0.5, method="m"
            )

    provider = _provider(ai_text_detector=FixedSignal())
    text_result = await provider.analyze(db=db, content_type="text", text="Some claim.", language="en")
    assert any(sig.id == "x" for sig in text_result.ai_signals)

    image_result = await provider.analyze(db=db, content_type="image", text="Some claim.", language="en")
    assert not any(sig.id == "x" for sig in image_result.ai_signals)


# ---- get_analysis_provider() switch ----


def _restore_fast_pipeline() -> None:
    # Same reasoning as test_analysis_provider.py's test_unknown_provider_raises: cache_clear()
    # just dropped tests/conftest.py's fast-pipeline override, which other tests in this
    # session rely on to not sleep for real.
    config.get_analysis_settings().pipeline_step_scale = 0.0


def test_groq_needs_groq_api_key(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PROVIDER", "groq")
    config.get_analysis_settings.cache_clear()
    try:
        with pytest.raises(NotImplementedError):
            get_analysis_provider()
    finally:
        monkeypatch.delenv("ANALYSIS_PROVIDER", raising=False)
        config.get_analysis_settings.cache_clear()
        _restore_fast_pipeline()


def test_groq_needs_tavily_api_key(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    config.get_analysis_settings.cache_clear()
    try:
        with pytest.raises(NotImplementedError):
            get_analysis_provider()
    finally:
        monkeypatch.delenv("ANALYSIS_PROVIDER", raising=False)
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        config.get_analysis_settings.cache_clear()
        _restore_fast_pipeline()


def test_groq_is_used_when_both_keys_are_set(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    config.get_analysis_settings.cache_clear()
    try:
        assert isinstance(get_analysis_provider(), GroqAnalysisProvider)
    finally:
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        config.get_analysis_settings.cache_clear()
        _restore_fast_pipeline()
