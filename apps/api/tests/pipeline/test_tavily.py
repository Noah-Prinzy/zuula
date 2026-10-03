"""tavily_search against respx mocks of Tavily's POST /search. Nothing calls the real
service."""

import json

import httpx
import pytest
import respx

from app.providers.tavily import TavilySearchError, tavily_search

URL = "https://tavily.example"
SEARCH = f"{URL}/search"


@respx.mock
async def test_search_returns_results():
    respx.post(SEARCH).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Fact-check: no free internet programme",
                        "url": "https://example.com/a",
                        "content": "The government has made no such announcement.",
                        "published_date": "2026-09-01",
                    },
                    {"title": "Untitled", "url": "https://example.com/b", "content": ""},
                ]
            },
        )
    )
    results = await tavily_search(api_key="test-key", api_url=URL, query="free internet Uganda")
    assert [r.url for r in results] == ["https://example.com/a", "https://example.com/b"]
    assert results[0].published_at == "2026-09-01"
    assert results[1].published_at is None


@respx.mock
async def test_search_sends_the_query_and_key():
    route = respx.post(SEARCH).mock(return_value=httpx.Response(200, json={"results": []}))
    await tavily_search(api_key="test-key", api_url=URL, query="some claim")
    body = json.loads(route.calls.last.request.content)
    assert body["api_key"] == "test-key" and body["query"] == "some claim"


@respx.mock
async def test_results_without_a_url_are_dropped():
    respx.post(SEARCH).mock(return_value=httpx.Response(200, json={"results": [{"title": "no url"}]}))
    assert await tavily_search(api_key="k", api_url=URL, query="q") == []


@respx.mock
async def test_an_http_error_raises():
    respx.post(SEARCH).mock(return_value=httpx.Response(401))
    with pytest.raises(TavilySearchError):
        await tavily_search(api_key="bad-key", api_url=URL, query="q")


@respx.mock
async def test_an_unparseable_response_raises():
    respx.post(SEARCH).mock(return_value=httpx.Response(200, text="not json"))
    with pytest.raises(TavilySearchError):
        await tavily_search(api_key="k", api_url=URL, query="q")
