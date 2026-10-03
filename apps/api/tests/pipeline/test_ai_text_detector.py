import pytest

from app.core import config
from app.providers.ai_text_detector import StubAiTextDetector, get_ai_text_detector


def test_stub_returns_no_signal():
    assert StubAiTextDetector().detect("Some submitted text.") is None


def test_get_ai_text_detector_returns_stub_by_default():
    assert isinstance(get_ai_text_detector(), StubAiTextDetector)


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("AI_TEXT_DETECTOR_PROVIDER", "made-up")
    config.get_analysis_settings.cache_clear()
    try:
        with pytest.raises(NotImplementedError):
            get_ai_text_detector()
    finally:
        monkeypatch.delenv("AI_TEXT_DETECTOR_PROVIDER", raising=False)
        config.get_analysis_settings.cache_clear()
        # Restore tests/conftest.py's fast-pipeline override, which cache_clear() just dropped.
        config.get_analysis_settings().pipeline_step_scale = 0.0
