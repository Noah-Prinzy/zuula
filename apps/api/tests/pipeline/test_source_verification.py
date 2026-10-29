"""TavilySourceVerifier: the Source Verification Engine's evidence gathering, isolated from
the Explanation Generator (test_explanation_generator.py covers that half). Against respx
mocks of Tavily's POST /search and the real test database for the trusted-source registry."""

import json

import httpx
import respx

from app.db import models as m
from app.providers.source_verification import TavilySourceVerifier, domain_of, is_trusted

URL = "https://tavily.example"
SEARCH = f"{URL}/search"


def _verifier(**overrides):
    kwargs = {"tavily_api_key": "tavily-key", "tavily_api_url": URL}
    kwargs.update(overrides)
    return TavilySourceVerifier(**kwargs)


async def _trusted_source(db, *, domain: str, source_id: str) -> m.TrustedSource:
    source = m.TrustedSource(
        id=source_id,
        name=domain,
        domain=domain,
        type="media",
        languages=["English"],
        tier=1,
        active=True,
    )
    db.add(source)
    await db.flush()
    return source


@respx.mock
async def test_gathers_evidence_and_returns_what_tavily_found(db):
    respx.post(SEARCH).mock(
        return_value=httpx.Response(
            200, json={"results": [{"title": "A", "url": "https://a.example", "content": "x"}]}
        )
    )
    evidence = await _verifier().gather_evidence(db, "some claim")
    # The seeded database already carries sample trusted sources (app/db/sample_data/
    # admin.py); this only proves gather_evidence reports *some* list, not an empty one.
    assert isinstance(evidence.trusted_domains, list)
    assert [s.url for s in evidence.sources] == ["https://a.example"]


@respx.mock
async def test_restricted_search_is_tried_first(db):
    await _trusted_source(db, domain="trusted-example.ug", source_id="src-sv-1")
    route = respx.post(SEARCH).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"title": "A", "url": "https://trusted-example.ug/a", "content": "a"},
                    {"title": "B", "url": "https://trusted-example.ug/b", "content": "b"},
                ]
            },
        )
    )
    evidence = await _verifier().gather_evidence(db, "some claim")
    assert route.call_count == 1
    body = json.loads(route.calls.last.request.content)
    # The seeded database already carries sample trusted sources alongside this one.
    assert "trusted-example.ug" in body["include_domains"]
    assert len(evidence.sources) == 2


@respx.mock
async def test_sparse_restricted_search_falls_back_to_unrestricted(db):
    await _trusted_source(db, domain="trusted-example.ug", source_id="src-sv-2")

    def _search(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "include_domains" in body:
            return httpx.Response(200, json={"results": []})
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": "A", "url": "https://open-example.com/a", "content": "a"},
                    {"title": "B", "url": "https://open-example.com/b", "content": "b"},
                ]
            },
        )

    route = respx.post(SEARCH).mock(side_effect=_search)
    evidence = await _verifier().gather_evidence(db, "some claim")
    assert route.call_count == 2
    assert [s.url for s in evidence.sources] == [
        "https://open-example.com/a",
        "https://open-example.com/b",
    ]


@respx.mock
async def test_a_tavily_failure_yields_no_evidence_rather_than_raising(db):
    respx.post(SEARCH).mock(return_value=httpx.Response(500))
    evidence = await _verifier().gather_evidence(db, "some claim")
    assert evidence.sources == []


def test_domain_of_strips_www():
    assert domain_of("https://www.monitor.co.ug/a") == "monitor.co.ug"
    assert domain_of("https://monitor.co.ug/a") == "monitor.co.ug"


def test_is_trusted_matches_subdomains():
    trusted = frozenset({"monitor.co.ug"})
    assert is_trusted("https://monitor.co.ug/a", trusted)
    assert is_trusted("https://news.monitor.co.ug/a", trusted)
    assert not is_trusted("https://example.com/a", trusted)


# ---- Exa as the backup search (Milestone D5) ----

EXA = "https://exa.example"


def _exa_results(*urls):
    return httpx.Response(
        200,
        json={
            "results": [
                {
                    "title": f"Title {u}",
                    "url": u,
                    "publishedDate": "2026-10-01T00:00:00.000Z",
                    "highlights": ["first passage", "second passage"],
                }
                for u in urls
            ]
        },
    )


@respx.mock
async def test_a_failing_tavily_goes_to_exa(db, caplog):
    respx.post(SEARCH).mock(return_value=httpx.Response(432))  # Tavily: quota used up
    exa = respx.post(f"{EXA}/search").mock(
        return_value=_exa_results("https://a.example/x", "https://b.example/y")
    )
    evidence = await _verifier(exa_api_key="exa-key", exa_api_url=EXA).gather_evidence(
        db, "some claim"
    )
    assert [s.url for s in evidence.sources] == ["https://a.example/x", "https://b.example/y"]
    first = evidence.sources[0]
    assert first.snippet == "first passage … second passage" and first.published_at == "2026-10-01"
    request = exa.calls[0].request
    assert request.headers["x-api-key"] == "exa-key"
    assert json.loads(request.content)["query"] == "some claim"
    assert "Tavily search failed with HTTP 432.; searching with Exa instead" in caplog.text


@respx.mock
async def test_both_failing_still_gives_a_bundle(db, caplog):
    respx.post(SEARCH).mock(side_effect=httpx.ConnectError("down"))
    respx.post(f"{EXA}/search").mock(return_value=httpx.Response(402))  # Exa: out of credit
    evidence = await _verifier(exa_api_key="exa-key", exa_api_url=EXA).gather_evidence(
        db, "some claim"
    )
    assert evidence.sources == []
    assert "Exa search failed with HTTP 402.; verifying without web evidence" in caplog.text


@respx.mock
async def test_without_an_exa_key_a_tavily_failure_means_no_evidence(db):
    respx.post(SEARCH).mock(return_value=httpx.Response(500))
    exa = respx.post(f"{EXA}/search")
    evidence = await _verifier(exa_api_url=EXA).gather_evidence(db, "some claim")
    assert evidence.sources == [] and not exa.called


@respx.mock
async def test_a_healthy_tavily_never_touches_exa(db):
    respx.post(SEARCH).mock(
        return_value=httpx.Response(
            200, json={"results": [{"title": "A", "url": "https://a.example", "content": "x"}]}
        )
    )
    exa = respx.post(f"{EXA}/search")
    await _verifier(exa_api_key="exa-key", exa_api_url=EXA).gather_evidence(db, "some claim")
    assert not exa.called
