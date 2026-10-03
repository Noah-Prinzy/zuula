"""AiTextDetector: the AI-generated-text signal in the `ai` step's AnalysisResult.ai_signals
(app/providers/analysis.py), for text submissions only.

`RobertaAiTextDetector` runs a small RoBERTa classifier in-process via `transformers`, on
CPU — no hosted endpoint, no monthly fee, same reasoning as app/providers/embedding.py for
defaulting AI_TEXT_DETECTOR_PROVIDER to `stub`: there's no key to gate on, and the model (and
`transformers`/`torch`) must never be pulled into the test suite by default.

The default model, openai-community/roberta-base-openai-detector, is OpenAI's own GPT-2
output detector — small, free and well-documented, but trained to catch GPT-2-era text, not
today's models. Its score is a rough signal for the report, not a verdict.

Deepfake detection (image/video) is a separate, explicitly deprioritized signal — see
app/providers/analysis.py — and has nothing to do with this module.
"""

import logging
from functools import lru_cache
from typing import Protocol

from app.core.config import get_analysis_settings
from app.schemas.fact_check import AISignal

logger = logging.getLogger("zuula.providers.ai_text_detector")

# Longest prefix handed to the classifier — RoBERTa's own context limit, not a Zuula choice.
_MAX_CHARS = 2000

# Label spellings seen on HuggingFace AI-text-detector model cards for "this is AI-generated"
# (as opposed to "Real"/"Human"/"LABEL_0"). Lower-cased before matching.
_AI_LABELS = frozenset({"fake", "ai", "ai-generated", "generated", "label_1"})


class AiTextDetector(Protocol):
    def detect(self, text: str) -> AISignal | None:
        """An AISignal estimating how likely `text` is AI-generated, or None when there's
        nothing to say (empty text, or the classifier failed)."""
        ...


class StubAiTextDetector:
    def detect(self, text: str) -> AISignal | None:
        return None


class RobertaAiTextDetector:
    def __init__(self, model_name: str):
        self._model_name = model_name

    def detect(self, text: str) -> AISignal | None:
        truncated = text.strip()[:_MAX_CHARS]
        if not truncated:
            return None
        try:
            scores = _load_pipeline(self._model_name)(truncated, top_k=None, truncation=True)
        except Exception:  # noqa: BLE001 — a classifier failure drops the signal, not the report
            logger.warning("AI-text detection failed", exc_info=True)
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
            id="ai-text-detector",
            label="AI-generated text",
            description=(
                "A RoBERTa classifier's estimate of how likely this text was AI-generated. "
                "Trained on older GPT-2-era output, not today's models — a rough signal, not "
                "a verdict."
            ),
            score=round(float(ai_score), 2),
            threshold=0.5,
            method=f"roberta:{self._model_name}",
        )


@lru_cache
def _load_pipeline(model_name: str):
    from transformers import pipeline

    return pipeline("text-classification", model=model_name, device=-1)


def get_ai_text_detector() -> AiTextDetector:
    """AI_TEXT_DETECTOR_PROVIDER: `roberta` for the real local classifier, `stub` (the
    default) otherwise."""
    settings = get_analysis_settings()
    choice = settings.ai_text_detector_provider.strip().lower()
    if choice not in ("stub", "roberta"):
        raise NotImplementedError(
            f"Unknown AI_TEXT_DETECTOR_PROVIDER '{settings.ai_text_detector_provider}': use "
            "'roberta' or 'stub'."
        )
    if choice == "stub":
        return StubAiTextDetector()
    return RobertaAiTextDetector(settings.ai_text_detector_model)
