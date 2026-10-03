import pytest

from app.core import config
from app.providers.analysis import StubAnalysisProvider, get_analysis_provider


async def test_stub_provider_is_deterministic(db):
    provider = StubAnalysisProvider()
    a = await provider.analyze(db=db, content_type="text", text="some claim", language="English")
    b = await provider.analyze(db=db, content_type="text", text="some claim", language="English")
    assert (a.title, a.verdict, a.confidence) == (b.title, b.verdict, b.confidence)


async def test_stub_provider_varies_by_input(db):
    provider = StubAnalysisProvider()
    a = await provider.analyze(db=db, content_type="text", text="claim one", language="English")
    b = await provider.analyze(
        db=db,
        content_type="text",
        text="a totally different claim entirely",
        language="English",
    )
    assert (a.title, a.verdict) != (b.title, b.verdict)


def test_get_analysis_provider_returns_stub_by_default():
    assert isinstance(get_analysis_provider(), StubAnalysisProvider)


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PROVIDER", "made-up-provider")
    config.get_analysis_settings.cache_clear()
    try:
        with pytest.raises(NotImplementedError):
            get_analysis_provider()
    finally:
        monkeypatch.delenv("ANALYSIS_PROVIDER", raising=False)
        config.get_analysis_settings.cache_clear()
        # Restore tests/conftest.py's fast-pipeline override, which cache_clear() above just
        # dropped — other tests in this session (tests/pipeline/test_pipeline_task.py) rely
        # on it to not spend real seconds sleeping through app/worker/pipeline.py's steps.
        config.get_analysis_settings().pipeline_step_scale = 0.0
