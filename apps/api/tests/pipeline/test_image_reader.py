"""app/providers/image_reader.py (Milestone D4): the vision request, the fallback chain and
the image shrinking. Against respx mocks; nothing calls a real service."""

import base64
import io
import json

import httpx
import pytest
import respx
from PIL import Image

from app.providers.explanation import ChatModel, GroqError
from app.providers.image_reader import (
    ImageReading,
    StubImageReader,
    VisionImageReader,
    get_image_reader,
    vision_models,
)

GROQ = "https://groq.example/openai/v1"
GEMINI = "https://gemini.example/v1beta/openai"


def _image(size=(3000, 2000)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, "navy").save(out, "PNG")
    return out.getvalue()


def _answer(**fields) -> httpx.Response:
    body = {"text": "", "claim": "", "description": ""} | fields
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(body)}}]})


def _reader():
    return VisionImageReader(
        (
            ChatModel(name="Groq", api_url=GROQ, api_key="k", model="qwen/qwen3.8-27b"),
            ChatModel(name="Gemini", api_url=GEMINI, api_key="g", model="gemini-3.1-flash-lite"),
        )
    )


@respx.mock
async def test_the_image_goes_as_a_shrunk_jpeg_and_the_reading_comes_back():
    route = respx.post(f"{GROQ}/chat/completions").mock(
        return_value=_answer(text=" FREE power ", claim="Power is free.", description="A poster.")
    )
    reading = await _reader().read(image=_image())
    assert reading == ImageReading(
        text="FREE power", claim="Power is free.", description="A poster."
    )

    content = json.loads(route.calls.last.request.content)["messages"][0]["content"]
    uri = next(part["image_url"]["url"] for part in content if part["type"] == "image_url")
    assert uri.startswith("data:image/jpeg;base64,")
    sent = Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1])))
    assert max(sent.size) == 1600


@respx.mock
async def test_a_failing_groq_goes_to_gemini():
    respx.post(f"{GROQ}/chat/completions").mock(return_value=httpx.Response(429))
    respx.post(f"{GEMINI}/chat/completions").mock(return_value=_answer(claim="From Gemini."))
    assert (await _reader().read(image=_image((50, 50)))).claim == "From Gemini."


@respx.mock
async def test_every_model_failing_raises():
    respx.post(f"{GROQ}/chat/completions").mock(return_value=httpx.Response(500))
    respx.post(f"{GEMINI}/chat/completions").mock(return_value=httpx.Response(503))
    with pytest.raises(GroqError):
        await _reader().read(image=_image((50, 50)))


def test_the_reading_as_text_to_check():
    reading = ImageReading(text="FREE power", claim="Power is free.", description="A poster.")
    assert reading.as_submission_text() == (
        "Power is free.\n\nText in the image: FREE power\n\nThe image shows: A poster."
    )
    assert ImageReading(text="", claim="", description="").as_submission_text() == ""


def test_models_and_factory(monkeypatch):
    from app.core import config

    def configure(**variables):
        for name, value in variables.items():
            monkeypatch.setenv(name, value)
        config.get_analysis_settings.cache_clear()

    for var in ("GROQ_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "ANALYSIS_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    configure()
    assert isinstance(get_image_reader(), StubImageReader)
    configure(GROQ_API_KEY="k", OPENROUTER_API_KEY="o")
    names = [(m.name, m.model) for m in vision_models(config.AnalysisSettings())]
    assert names == [
        ("Groq", "qwen/qwen3.8-27b"),
        ("OpenRouter", "nvidia/nemotron-3.5-super-vl:free"),
    ]
    assert isinstance(get_image_reader(), VisionImageReader)
    configure(ANALYSIS_PROVIDER="stub")
    assert isinstance(get_image_reader(), StubImageReader)
    monkeypatch.undo()
    config.get_analysis_settings.cache_clear()
    config.get_analysis_settings().pipeline_step_scale = 0.0
