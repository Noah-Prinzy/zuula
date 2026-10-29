"""Exa web search: the backup for Tavily in the `sources` step (Milestone D5). On 28 Oct 2026
Tavily's free monthly quota ran out and every check went on without web evidence, silently.
app/providers/source_verification.py's TavilySourceVerifier now tries Exa whenever Tavily
fails. Free tier (Oct 2026): $10 of credit a month, no card; a search with highlights is
about $0.007, so roughly 1,400 backup searches a month.

Returns the same TavilyResult shape and raises the same TavilySearchError as Tavily, so the
verifier treats both alike.
"""

import httpx

from app.providers.tavily import TavilyResult, TavilySearchError


async def exa_search(
    *,
    api_key: str,
    api_url: str,
    query: str,
    max_results: int = 5,
    timeout: float = 20.0,
    include_domains: list[str] | None = None,
) -> list[TavilyResult]:
    # Checked against Exa's build-with-exa skill (29 Oct 2026): `auto` is its recommended
    # type; highlights alone (not stacked with text/summary) are the passages most relevant
    # to the query, the closest thing to Tavily's `content`. Two deliberate departures from
    # its bare defaults: maxCharacters 500 is the verdict prompt's per-source budget
    # (explanation.py's _sources_block), and numResults matches Tavily's count.
    payload: dict = {
        "query": query,
        "numResults": max_results,
        "type": "auto",
        "contents": {"highlights": {"maxCharacters": 500}},
    }
    # Only the admin-approved trusted-source registry is ever passed here (the hard
    # allowlist the skill reserves includeDomains for); the open search follows if it's thin.
    if include_domains:
        payload["includeDomains"] = include_domains
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{api_url.rstrip('/')}/search", json=payload, headers={"x-api-key": api_key}
            )
    except httpx.HTTPError as exc:
        raise TavilySearchError(f"Exa search failed ({type(exc).__name__}).") from exc
    # Never include the response body: a 4xx can echo the query back. 402: out of credit.
    if response.status_code >= 400:
        raise TavilySearchError(f"Exa search failed with HTTP {response.status_code}.")
    try:
        results = response.json()["results"]
    except (ValueError, KeyError) as exc:
        raise TavilySearchError("Exa returned something unexpected.") from exc
    return [
        TavilyResult(
            title=str(r.get("title") or r.get("url") or "Untitled source"),
            url=str(r.get("url") or ""),
            snippet=" … ".join(r.get("highlights") or []) or str(r.get("text") or ""),
            published_at=(r.get("publishedDate") or "")[:10] or None,
        )
        for r in results
        if r.get("url")
    ][:max_results]
