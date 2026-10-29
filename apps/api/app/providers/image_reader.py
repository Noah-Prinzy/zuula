"""ImageReader: what an uploaded image says (Milestone D4). Before this, nothing looked at the
picture, so every image came back "unverifiable" (fc-2026-0167). The pipeline's `media` step
asks a vision model for the image's text and the factual claim it makes, and the claim goes
through the same search + verdict as a text submission.

The models are OpenAI-compatible chat endpoints taking the image as a data URI, tried in
order like the verdict's (app/providers/explanation.py's `first_json`): Groq's
GROQ_VISION_MODEL, then each GEMINI_MODEL, then OPENROUTER_VISION_MODEL. Tested on
29 Oct 2026 with a fake "free electricity" graphic: Groq qwen/qwen3.8-27b 1.4 s, OpenRouter
nvidia/nemotron-3.5-super-vl:free 6.5 s, both read every line and stated the claim.
"""

import base64
import io
import logging
from dataclasses import dataclass
from typing import Protocol

from app.core.config import AnalysisSettings, get_analysis_settings
from app.providers.explanation import ChatModel, first_json

logger = logging.getLogger("zuula.providers.image_reader")

# Longest side sent to the model. Groq takes base64 images up to 4 MB; a phone photo is
# larger, and text stays legible at this size.
_MAX_SIDE = 1600

_PROMPT = """\
You are helping a Ugandan fact-checking service. Read this image and reply with ONLY a JSON \
object of this exact shape:

{
  "text": every piece of text visible in the image, as written (any language), "" if none,
  "claim": the main factual claim the image makes or implies, as one plain English sentence, \
"" if it makes none,
  "description": one sentence describing what the image shows
}

Report what the image says; don't judge whether it's true."""


@dataclass
class ImageReading:
    text: str
    claim: str
    description: str

    def as_submission_text(self) -> str:
        """What the claims/sources/ai steps check, in place of a text submission's body."""
        parts = [self.claim]
        if self.text:
            parts.append(f"Text in the image: {self.text}")
        if self.description:
            parts.append(f"The image shows: {self.description}")
        return "\n\n".join(p for p in parts if p)


class ImageReader(Protocol):
    async def read(self, *, image: bytes) -> ImageReading: ...


class StubImageReader:
    """Local dev and the tests: reads nothing, so an image is checked on its headline alone
    (the behaviour before D4)."""

    async def read(self, *, image: bytes) -> ImageReading:
        return ImageReading(text="", claim="", description="")


class VisionImageReader:
    def __init__(self, models: tuple[ChatModel, ...], *, timeout: float = 30.0):
        self._models = models
        self._timeout = timeout

    async def read(self, *, image: bytes) -> ImageReading:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _PROMPT},
                    {"type": "image_url", "image_url": {"url": _data_uri(image)}},
                ],
            }
        ]
        data, _ = await first_json(
            self._models, messages, timeout=self._timeout, what="image reading"
        )
        return ImageReading(
            text=str(data.get("text") or "").strip(),
            claim=str(data.get("claim") or "").strip(),
            description=str(data.get("description") or "").strip(),
        )


def _data_uri(image: bytes) -> str:
    """The image as a JPEG data URI no larger than _MAX_SIDE (EXIF orientation applied)."""
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(image)) as opened:
        picture = ImageOps.exif_transpose(opened).convert("RGB")
    picture.thumbnail((_MAX_SIDE, _MAX_SIDE))
    out = io.BytesIO()
    picture.save(out, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()


def vision_models(settings: AnalysisSettings) -> tuple[ChatModel, ...]:
    """Groq's vision model, then every Gemini model, then OpenRouter's vision models; each
    provider only when its key is set."""
    providers = (
        ("Groq", settings.groq_api_url, settings.groq_api_key, settings.groq_vision_model),
        ("Gemini", settings.gemini_api_url, settings.gemini_api_key, settings.gemini_model),
        (
            "OpenRouter",
            settings.openrouter_api_url,
            settings.openrouter_api_key,
            settings.openrouter_vision_model,
        ),
    )
    return tuple(
        ChatModel(name=name, api_url=url, api_key=key, model=model.strip())
        for name, url, key, models in providers
        if key
        for model in models.split(",")
        if model.strip()
    )


def get_image_reader() -> ImageReader:
    """The vision chain when ANALYSIS_PROVIDER would be real (a Groq key, not `stub`), the
    stub otherwise — the same real-when-configured rule as the verdict."""
    settings = get_analysis_settings()
    if settings.analysis_provider.strip().lower() == "stub":
        return StubImageReader()
    models = vision_models(settings)
    return VisionImageReader(models) if models else StubImageReader()
