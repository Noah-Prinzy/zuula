"""Tavily web search: the `sources` step's evidence retrieval
(app/providers/analysis.py's GroqAnalysisProvider). One search per claim, free tier
(1,000 searches/month) — no agent loop, just the results handed straight to the single Groq
generation call.
"""

from dataclasses import dataclass

import httpx


class TavilySearchError(Exception):
    """A search failed; app/providers/analysis.py treats this as "no evidence found" rather
    than failing the whole analysis — a missing search result shouldn't block a verdict."""


@dataclass
class TavilyResult:
    title: str
    url: str
    snippet: str
    published_at: str | None  # ISO date, when Tavily reports one


async def tavily_search(
    *, api_key: str, api_url: str, query: str, max_results: int = 5, timeout: float = 20.0
) -> list[TavilyResult]:
    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": "basic",
        "max_results": max_results,
        "include_answer": False,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{api_url.rstrip('/')}/search", json=payload)
    except httpx.HTTPError as exc:
        raise TavilySearchError("Tavily search failed.") from exc
    # Never include the response body: a 4xx can echo the query (and the key) back.
    if response.status_code >= 400:
        raise TavilySearchError(f"Tavily search failed with HTTP {response.status_code}.")
    try:
        results = response.json()["results"]
    except (ValueError, KeyError) as exc:
        raise TavilySearchError("Tavily returned something unexpected.") from exc
    return [
        TavilyResult(
            title=str(r.get("title") or r.get("url") or "Untitled source"),
            url=str(r.get("url") or ""),
            snippet=str(r.get("content") or ""),
            published_at=r.get("published_date") or None,
        )
        for r in results
        if r.get("url")
    ][:max_results]
