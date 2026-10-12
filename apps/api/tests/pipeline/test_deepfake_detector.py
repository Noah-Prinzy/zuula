"""DeepfakeDetector: the stub, the provider switch, and TransformersDeepfakeDetector's label
interpretation with `_load_pipeline` monkeypatched to a fixed classifier — the test suite
never downloads the real pretrained model (same convention as test_ai_text_detector.py for
RobertaAiTextDetector)."""

import pytest

from app.core import config
from app.providers import deepfake_detector as module
from app.providers.deepfake_detector import (
    StubDeepfakeDetector,
    TransformersDeepfakeDetector,
    get_deepfake_detector,
)


def _tiny_jpeg() -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color="blue").save(buf, format="JPEG")
    return buf.getvalue()


def test_stub_returns_no_signal():
    assert StubDeepfakeDetector().detect(b"anything") is None


def test_empty_bytes_return_none():
    assert TransformersDeepfakeDetector("fake/model").detect(b"") is None


def test_fake_label_raises_the_score(monkeypatch):
    monkeypatch.setattr(
        module,
        "_load_pipeline",
        lambda model_name: lambda image, top_k=None: [
            {"label": "artificial", "score": 0.91},
            {"label": "real", "score": 0.09},
        ],
    )
    signal = TransformersDeepfakeDetector("fake/model").detect(_tiny_jpeg())
    assert signal is not None
    assert signal.score == 0.91
    assert signal.id == "deepfake-detector"
    assert signal.method == "transformers:fake/model"


def test_real_only_label_is_inverted(monkeypatch):
    monkeypatch.setattr(
        module,
        "_load_pipeline",
        lambda model_name: lambda image, top_k=None: [{"label": "Real", "score": 0.8}],
    )
    signal = TransformersDeepfakeDetector("fake/model").detect(_tiny_jpeg())
    assert signal.score == pytest.approx(0.2)


def test_a_classifier_failure_returns_none(monkeypatch):
    def _boom(model_name):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(module, "_load_pipeline", _boom)
    assert TransformersDeepfakeDetector("fake/model").detect(_tiny_jpeg()) is None


def test_undecodable_bytes_return_none():
    assert TransformersDeepfakeDetector("fake/model").detect(b"not an image") is None


# ---- get_deepfake_detector() switch ----


def test_defaults_to_stub():
    assert isinstance(get_deepfake_detector(), StubDeepfakeDetector)


def test_transformers_provider_is_used_when_configured(monkeypatch):
    monkeypatch.setenv("DEEPFAKE_DETECTOR_PROVIDER", "transformers")
    config.get_analysis_settings.cache_clear()
    try:
        assert isinstance(get_deepfake_detector(), TransformersDeepfakeDetector)
    finally:
        monkeypatch.delenv("DEEPFAKE_DETECTOR_PROVIDER", raising=False)
        config.get_analysis_settings.cache_clear()


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("DEEPFAKE_DETECTOR_PROVIDER", "made-up")
    config.get_analysis_settings.cache_clear()
    try:
        with pytest.raises(NotImplementedError):
            get_deepfake_detector()
    finally:
        monkeypatch.delenv("DEEPFAKE_DETECTOR_PROVIDER", raising=False)
        config.get_analysis_settings.cache_clear()
