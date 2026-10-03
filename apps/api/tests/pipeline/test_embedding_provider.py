import pytest

from app.core import config
from app.providers.embedding import (
    EMBEDDING_DIMENSIONS,
    StubEmbeddingProvider,
    get_embedding_provider,
)


def test_stub_is_deterministic_across_instances():
    a = StubEmbeddingProvider().embed("The minister announced a new policy today.")
    b = StubEmbeddingProvider().embed("The minister announced a new policy today.")
    assert a == b
    assert len(a) == EMBEDDING_DIMENSIONS


def test_stub_differs_for_unrelated_text():
    a = StubEmbeddingProvider().embed("Free internet for every Ugandan from January.")
    b = StubEmbeddingProvider().embed("The president opened a new hospital in Mbale.")
    assert a != b


def test_stub_handles_empty_text():
    assert StubEmbeddingProvider().embed("") == [0.0] * EMBEDDING_DIMENSIONS


def test_get_embedding_provider_returns_stub_by_default():
    assert isinstance(get_embedding_provider(), StubEmbeddingProvider)


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "made-up")
    config.get_analysis_settings.cache_clear()
    try:
        with pytest.raises(NotImplementedError):
            get_embedding_provider()
    finally:
        monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
        config.get_analysis_settings.cache_clear()
        # Restore tests/conftest.py's fast-pipeline override, which cache_clear() just dropped.
        config.get_analysis_settings().pipeline_step_scale = 0.0
