"""The `fetch` step (URL submissions): downloading the page and pulling out the article
text, replacing app/worker/pipeline.py's old demo-only "a URL containing 'fail' can't be
fetched" placeholder with a real fetch.

trafilatura (https://trafilatura.readthedocs.io) does both the download and the extraction;
it's self-hosted, free and needs no API key, so there's no stub/real switch here the way
there is for the providers that call a paid hosted service — tests instead monkeypatch
`trafilatura.fetch_url`/`trafilatura.extract` directly (see tests/pipeline/test_fetch.py).

trafilatura's own HTTP client is synchronous, so both calls run in a thread
(asyncio.to_thread) rather than blocking the worker's event loop.
"""

import asyncio

import trafilatura


class FetchError(Exception):
    """The URL couldn't be downloaded, or no article text could be pulled out of it. Its
    message is shown to the submitter as-is (app/worker/pipeline.py's failure path), so it
    stays short and free of anything from the response body."""


class TrafilaturaArticleFetcher:
    async def fetch(self, *, url: str) -> str:
        try:
            downloaded = await asyncio.to_thread(trafilatura.fetch_url, url)
        except Exception as exc:  # noqa: BLE001 — trafilatura mostly returns None on failure,
            # but fails closed on whatever it doesn't swallow itself too.
            raise FetchError("Couldn't fetch that link.") from exc
        if not downloaded:
            raise FetchError("Couldn't fetch that link.")
        text = await asyncio.to_thread(trafilatura.extract, downloaded, url=url)
        if not text or not text.strip():
            raise FetchError("Couldn't find an article in that link.")
        return text.strip()


def get_article_fetcher() -> TrafilaturaArticleFetcher:
    return TrafilaturaArticleFetcher()
