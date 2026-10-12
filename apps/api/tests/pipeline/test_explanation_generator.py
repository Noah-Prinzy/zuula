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
    kwargs = {"groq_api_key": "groq-key", "groq_api_url": URL, "groq_model": "llama-3.3-70b-versatile"}
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
        content_type="text", text="some claim", evidence=EvidenceBundle(sources=[], trusted_domains=[])
    )
    assert explanation.verdict == "false"
    assert explanation.summary == "Unverifiable, no evidence."


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
