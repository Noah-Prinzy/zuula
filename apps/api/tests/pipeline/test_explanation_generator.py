"""GroqExplanationGenerator: the Explanation Generator's wording of a verdict from a given
EvidenceBundle, isolated from the Source Verification Engine (test_source_verification.py
covers that half — this file builds EvidenceBundle values by hand). Against respx mocks of
Groq's chat completions endpoint. Nothing calls a real service."""

import json

import httpx
import pytest
import respx

from app.providers.explanation import GroqError, GroqExplanationGenerator
from app.providers.source_verification import EvidenceBundle
from app.providers.tavily import TavilyResult

URL = "https://groq.example"
CHAT = f"{URL}/chat/completions"


def _generator(**overrides):
    kwargs = {
        "groq_api_key": "groq-key",
        "groq_api_url": URL,
        "groq_model": "llama-3.3-70b-versatile",
    }
    kwargs.update(overrides)
    return GroqExplanationGenerator(**kwargs)


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


@respx.mock
async def test_generates_an_explanation_with_no_evidence():
    respx.post(CHAT).mock(return_value=_verdict_response(summary="Unverifiable, no evidence."))
    explanation = await _generator().generate(
        content_type="text",
        text="some claim",
        evidence=EvidenceBundle(sources=[], trusted_domains=[]),
    )
    assert explanation.verdict == "false"
    assert explanation.summary == "Unverifiable, no evidence."
    assert explanation.confidence == 60  # 85, capped: nothing cited


_ONE_SOURCE = EvidenceBundle(
    sources=[TavilyResult(title="A", url="https://a.example", snippet="x", published_at=None)],
    trusted_domains=[],
)


@respx.mock
async def test_authentic_with_nothing_cited_becomes_unverifiable():
    respx.post(CHAT).mock(
        return_value=_verdict_response(verdict="authentic", confidence=95, summary="It happened.")
    )
    explanation = await _generator().generate(
        content_type="text", text="This picture shows a flooded hospital", evidence=_ONE_SOURCE
    )
    assert explanation.verdict == "unverifiable"
    assert explanation.confidence == 60
    assert explanation.summary.startswith("It happened. No source found confirms it")


@respx.mock
async def test_authentic_with_only_context_sources_becomes_unverifiable():
    respx.post(CHAT).mock(
        return_value=_verdict_response(
            verdict="authentic",
            confidence=95,
            citationStances=[{"index": 0, "stance": "context"}],
        )
    )
    explanation = await _generator().generate(
        content_type="text", text="claim", evidence=_ONE_SOURCE
    )
    assert explanation.verdict == "unverifiable"
    assert explanation.confidence == 60


@respx.mock
async def test_authentic_with_a_supporting_source_keeps_its_confidence():
    respx.post(CHAT).mock(
        return_value=_verdict_response(
            verdict="authentic",
            confidence=95,
            citationStances=[{"index": 0, "stance": "supports"}],
        )
    )
    explanation = await _generator().generate(
        content_type="text", text="claim", evidence=_ONE_SOURCE
    )
    assert explanation.verdict == "authentic"
    assert explanation.confidence == 95


def _supported_authentic() -> httpx.Response:
    return _verdict_response(
        verdict="authentic",
        confidence=92,
        summary="The floods happened.",
        citationStances=[{"index": 0, "stance": "supports"}],
    )


@pytest.mark.parametrize(
    "text",
    ["Photo of Kenyans queuing for food", "Video shows flooding in Nairobi", "Photos of the drought"],
)
@respx.mock
async def test_an_unseen_media_caption_is_never_authentic(text):
    respx.post(CHAT).mock(return_value=_supported_authentic())
    explanation = await _generator().generate(content_type="text", text=text, evidence=_ONE_SOURCE)
    assert explanation.verdict == "unverifiable"
    assert explanation.confidence == 60
    assert "hasn't seen the photo or video" in explanation.summary


@respx.mock
async def test_a_media_caption_with_an_image_reading_can_be_authentic():
    respx.post(CHAT).mock(return_value=_supported_authentic())
    text = "Photo of floods in West Pokot\n\nThe image shows: a flooded road with a bus"
    explanation = await _generator().generate(content_type="image", text=text, evidence=_ONE_SOURCE)
    assert explanation.verdict == "authentic"
    assert explanation.confidence == 92


@respx.mock
async def test_a_claim_merely_mentioning_a_video_isnt_a_caption():
    respx.post(CHAT).mock(return_value=_supported_authentic())
    text = "The ministry released a video statement on the floods"
    explanation = await _generator().generate(content_type="text", text=text, evidence=_ONE_SOURCE)
    assert explanation.verdict == "authentic"


@respx.mock
async def test_the_prompt_treats_media_captions_as_claims_about_the_media():
    route = respx.post(CHAT).mock(return_value=_verdict_response())
    await _generator().generate(content_type="text", text="claim", evidence=_ONE_SOURCE)
    system = json.loads(route.calls[0].request.content)["messages"][0]["content"]
    assert "claim about that media" in system
    assert 'Say "authentic" only when at least one evidence item supports' in system


@respx.mock
async def test_citations_are_built_only_for_cited_sources_and_marked_trusted():
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
    evidence = EvidenceBundle(
        sources=[
            TavilyResult(title="A", url="https://a.example", snippet="x", published_at=None),
            TavilyResult(
                title="B", url="https://trusted.example", snippet="y", published_at="2026-01-01"
            ),
        ],
        trusted_domains=["trusted.example"],
    )
    explanation = await _generator().generate(content_type="text", text=text, evidence=evidence)

    assert [c.url for c in explanation.citations] == ["https://trusted.example"]
    assert explanation.citations[0].stance == "contradicts"
    assert explanation.citations[0].trusted is True
    assert len(explanation.claims) == 1
    claim = explanation.claims[0]
    assert claim.citation_ids == [explanation.citations[0].id]
    assert text[claim.start : claim.end] == "a new hospital"


@respx.mock
async def test_local_evidence_sources_are_always_trusted_and_labeled_distinctly():
    captured: dict = {}

    def _chat(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _verdict_response(
            citationStances=[
                {"index": 0, "stance": "contradicts"},
                {"index": 1, "stance": "context"},
            ]
        )

    respx.post(CHAT).mock(side_effect=_chat)
    evidence = EvidenceBundle(
        sources=[
            TavilyResult(
                title="Prior debunk",
                url="https://factcheck.example/x",
                snippet="z",
                published_at="2025-01-01",
            ),
            TavilyResult(
                title="A", url="https://untrusted.example", snippet="y", published_at=None
            ),
        ],
        trusted_domains=[],  # neither factcheck.example nor untrusted.example is registered
        local_evidence_count=1,
    )
    explanation = await _generator().generate(content_type="text", text="x", evidence=evidence)

    by_url = {c.url: c for c in explanation.citations}
    assert by_url["https://factcheck.example/x"].trusted is True
    assert by_url["https://untrusted.example"].trusted is False

    prompt = captured["body"]["messages"][1]["content"]
    assert "[0] (Zuula's own verified fact-check corpus)" in prompt
    assert "[1] (live web search)" in prompt


@respx.mock
async def test_an_http_error_raises_groq_error():
    respx.post(CHAT).mock(return_value=httpx.Response(500))
    with pytest.raises(GroqError):
        await _generator().generate(
            content_type="text", text="x", evidence=EvidenceBundle(sources=[], trusted_domains=[])
        )


@respx.mock
async def test_malformed_json_raises_groq_error():
    respx.post(CHAT).mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})
    )
    with pytest.raises(GroqError):
        await _generator().generate(
            content_type="text", text="x", evidence=EvidenceBundle(sources=[], trusted_domains=[])
        )


@respx.mock
async def test_an_invalid_verdict_falls_back_to_unverifiable():
    respx.post(CHAT).mock(return_value=_verdict_response(verdict="not-a-real-verdict"))
    explanation = await _generator().generate(
        content_type="text", text="x", evidence=EvidenceBundle(sources=[], trusted_domains=[])
    )
    assert explanation.verdict == "unverifiable"


# ---- Fallback chain (Milestone D3) ----

GEMINI = "https://gemini.example/v1beta/openai"
OPENROUTER = "https://openrouter.example/api/v1"
NO_EVIDENCE = EvidenceBundle(sources=[], trusted_domains=[])


def _chain():
    from app.providers.explanation import ChatModel

    return _generator(
        fallbacks=(
            ChatModel(name="Gemini", api_url=GEMINI, api_key="g", model="gemini-2.5-flash"),
            ChatModel(name="OpenRouter", api_url=OPENROUTER, api_key="o", model="llama:free"),
        )
    )


@pytest.mark.parametrize(
    "groq_failure",
    [
        httpx.Response(429, json={"error": {"message": "tokens per day"}}),
        httpx.Response(503),
        httpx.ConnectTimeout("timed out"),
        httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]}),
    ],
)
@respx.mock
async def test_a_groq_failure_goes_to_gemini(groq_failure, caplog):
    groq = respx.post(CHAT)
    if isinstance(groq_failure, Exception):
        groq.mock(side_effect=groq_failure)
    else:
        groq.mock(return_value=groq_failure)
    gemini = respx.post(f"{GEMINI}/chat/completions").mock(
        return_value=_verdict_response(summary="From Gemini.")
    )
    explanation = await _chain().generate(content_type="text", text="x", evidence=NO_EVIDENCE)
    assert explanation.summary == "From Gemini."
    assert json.loads(gemini.calls.last.request.content)["model"] == "gemini-2.5-flash"
    assert gemini.calls.last.request.headers["Authorization"] == "Bearer g"
    assert "The verdict came from fallback Gemini" in caplog.text


@respx.mock
async def test_openrouter_is_tried_after_gemini_and_fences_are_tolerated():
    respx.post(CHAT).mock(return_value=httpx.Response(500))
    respx.post(f"{GEMINI}/chat/completions").mock(return_value=httpx.Response(429))
    fenced = "```json\n" + json.dumps({"verdict": "false", "summary": "From OpenRouter."}) + "\n```"
    respx.post(f"{OPENROUTER}/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": fenced}}]})
    )
    explanation = await _chain().generate(content_type="text", text="x", evidence=NO_EVIDENCE)
    assert explanation.summary == "From OpenRouter."


@respx.mock
async def test_groq_error_only_when_every_model_failed():
    respx.post(CHAT).mock(return_value=httpx.Response(500))
    respx.post(f"{GEMINI}/chat/completions").mock(return_value=httpx.Response(401))
    respx.post(f"{OPENROUTER}/chat/completions").mock(return_value=httpx.Response(503))
    with pytest.raises(GroqError) as raised:
        await _chain().generate(content_type="text", text="x", evidence=NO_EVIDENCE)
    message = str(raised.value)
    assert "Groq" in message and "Gemini" in message and "OpenRouter" in message


@respx.mock
async def test_a_healthy_groq_never_touches_the_fallbacks():
    respx.post(CHAT).mock(return_value=_verdict_response())
    gemini = respx.post(f"{GEMINI}/chat/completions")
    await _chain().generate(content_type="text", text="x", evidence=NO_EVIDENCE)
    assert not gemini.called


def test_fallbacks_are_only_the_ones_with_keys(monkeypatch):
    from app.core.config import AnalysisSettings
    from app.providers.analysis import fallback_models

    for var in ("GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert fallback_models(AnalysisSettings(_env_file=None)) == ()
    monkeypatch.setenv("OPENROUTER_API_KEY", "o")
    monkeypatch.setenv("OPENROUTER_MODEL", "a:free, b:free,")
    models = fallback_models(AnalysisSettings(_env_file=None))
    assert [(m.name, m.model) for m in models] == [("OpenRouter", "a:free"), ("OpenRouter", "b:free")]
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-x")
    models = fallback_models(AnalysisSettings(_env_file=None))
    assert [m.model for m in models] == ["gemini-x", "a:free", "b:free"]
