"""TrafilaturaArticleFetcher: the `fetch` step's real article extraction. No network — both
of trafilatura's own calls are monkeypatched, same as tests/pipeline/test_pipeline_task.py's
_mock_article_fetch fixture does for the full pipeline."""

import pytest
import trafilatura

from app.providers.fetch import FetchError, TrafilaturaArticleFetcher

fetcher = TrafilaturaArticleFetcher()


async def test_fetch_extracts_the_article(monkeypatch):
    monkeypatch.setattr(trafilatura, "fetch_url", lambda url: "<html>raw</html>")
    monkeypatch.setattr(
        trafilatura, "extract", lambda html, **kwargs: "  The article's text.  "
    )
    assert await fetcher.fetch(url="https://example.com/a") == "The article's text."


async def test_a_download_failure_raises(monkeypatch):
    monkeypatch.setattr(trafilatura, "fetch_url", lambda url: None)
    with pytest.raises(FetchError):
        await fetcher.fetch(url="https://example.com/a")


async def test_an_empty_extraction_raises(monkeypatch):
    monkeypatch.setattr(trafilatura, "fetch_url", lambda url: "<html></html>")
    monkeypatch.setattr(trafilatura, "extract", lambda html, **kwargs: None)
    with pytest.raises(FetchError):
        await fetcher.fetch(url="https://example.com/a")


async def test_an_unexpected_exception_is_wrapped(monkeypatch):
    def boom(url):
        raise RuntimeError("network stack exploded")

    monkeypatch.setattr(trafilatura, "fetch_url", boom)
    with pytest.raises(FetchError):
        await fetcher.fetch(url="https://example.com/a")
