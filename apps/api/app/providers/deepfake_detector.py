"""DeepfakeDetector: a basic AI-generated/synthetic-image signal for image submissions'
ai_signals (app/providers/analysis.py), using a pretrained open-weight classifier — no
training, no GPU. §5.3's CNNDetection/FaceForensics++-style trained deepfake detectors are
explicitly out of scope for this project (no labelled corpus, no GPU budget — see the P4
brief); this is the achievable alternative the spec's own "AI Content Detection Module"
(§4.1) can use instead of nothing.

Same real-or-stub convention as app/providers/ai_text_detector.py: the default model,
`umm-maybe/AI-image-detector` (a ViT image classifier publicly hosted on Hugging Face,
fine-tuned to separate AI-generated images from camera-captured ones), runs in-process via
`transformers`, on CPU, no key, no monthly fee. DEEPFAKE_DETECTOR_PROVIDER defaults to `stub`
for the same reason as EMBEDDING_PROVIDER/AI_TEXT_DETECTOR_PROVIDER: there's no credential to
gate on, and the model download must never happen in routine dev/CI.

This is a basic AI-image signal, not deepfake-specific forensics (no face-swap or
lip-sync analysis) — it says "does this look machine-generated," not "is this a doctored
video of a real person." That distinction belongs in the report's description, not just this
docstring.
"""

import logging
from functools import lru_cache
from typing import Protocol

from app.core.config import get_analysis_settings
from app.schemas.fact_check import AISignal

logger = logging.getLogger("zuula.providers.deepfake_detector")

# Label spellings seen on HuggingFace AI-image-detector model cards for "this looks
# AI-generated" (as opposed to "Real"/"Human"/"LABEL_0"). Lower-cased before matching — same
# convention as app/providers/ai_text_detector.py's _AI_LABELS.
_AI_LABELS = frozenset({"artificial", "ai", "ai-generated", "fake", "generated", "label_1"})


class DeepfakeDetector(Protocol):
    def detect(self, data: bytes) -> AISignal | None:
        """An AISignal estimating how likely an image is AI-generated/synthetic, or None when
        there's nothing to say (empty input, or the classifier/decoder failed)."""
        ...


class StubDeepfakeDetector:
    def detect(self, data: bytes) -> AISignal | None:
        return None


class TransformersDeepfakeDetector:
    def __init__(self, model_name: str):
        self._model_name = model_name

    def detect(self, data: bytes) -> AISignal | None:
        if not data:
            return None
        try:
            image = _load_image(data)
            scores = _load_pipeline(self._model_name)(image, top_k=None)
        except Exception:  # noqa: BLE001 — a classifier failure drops the signal, not the report
            logger.warning("Deepfake detection failed", exc_info=True)
            return None
        if isinstance(scores, list) and scores and isinstance(scores[0], list):
            scores = scores[0]  # some transformers versions nest a one-item batch
        ai_score = next(
            (s["score"] for s in scores if str(s.get("label", "")).lower() in _AI_LABELS),
            1.0 - scores[0]["score"] if scores else None,
        )
        if ai_score is None:
            return None
        return AISignal(
            id="deepfake-detector",
            label="AI-generated image",
            description=(
                "A pretrained image classifier's estimate of how likely this image is "
                "AI-generated or synthetic, rather than camera-captured. A basic signal, not "
                "deepfake-specific forensics — no face-swap or lip-sync model was trained for "
                "this project."
            ),
            score=round(float(ai_score), 2),
            threshold=0.5,
            method=f"transformers:{self._model_name}",
        )


def _load_image(data: bytes):
    import io

    from PIL import Image

    return Image.open(io.BytesIO(data)).convert("RGB")


@lru_cache
def _load_pipeline(model_name: str):
    from transformers import pipeline

    return pipeline("image-classification", model=model_name, device=-1)


def get_deepfake_detector() -> DeepfakeDetector:
    """DEEPFAKE_DETECTOR_PROVIDER: `transformers` for the real local classifier, `stub` (the
    default) otherwise."""
    settings = get_analysis_settings()
    choice = settings.deepfake_detector_provider.strip().lower()
    if choice not in ("stub", "transformers"):
        raise NotImplementedError(
            f"Unknown DEEPFAKE_DETECTOR_PROVIDER '{settings.deepfake_detector_provider}': use "
            "'transformers' or 'stub'."
        )
    if choice == "stub":
        return StubDeepfakeDetector()
    return TransformersDeepfakeDetector(settings.deepfake_detector_model)
