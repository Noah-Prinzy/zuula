"""GroqWhisperProvider against respx mocks of Groq's OpenAI-compatible
POST /audio/transcriptions. Nothing calls the real service."""

import httpx
import pytest
import respx

from app.providers.transcription import (
    GroqWhisperProvider,
    StubTranscriptionProvider,
    TranscriptionError,
)

URL = "https://groq.example"
TRANSCRIPTIONS = f"{URL}/audio/transcriptions"
groq = GroqWhisperProvider(api_url=URL, api_key="test-key", model="whisper-large-v3-turbo")


async def test_stub_tags_its_output():
    text = await StubTranscriptionProvider().transcribe(audio=b"abc", content_type="audio/mpeg")
    assert text.startswith("[stub-transcription audio/mpeg]")


@respx.mock
async def test_transcribe_sends_the_audio_and_model():
    route = respx.post(TRANSCRIPTIONS).mock(
        return_value=httpx.Response(200, json={"text": "Hello, how are you?"})
    )
    text = await groq.transcribe(audio=b"fake-audio-bytes", content_type="audio/mpeg")
    assert text == "Hello, how are you?"
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer test-key"
    assert b'name="model"' in request.content and b"whisper-large-v3-turbo" in request.content
    assert b'filename="upload.mp3"' in request.content


@respx.mock
async def test_an_http_error_raises():
    respx.post(TRANSCRIPTIONS).mock(return_value=httpx.Response(500))
    with pytest.raises(TranscriptionError):
        await groq.transcribe(audio=b"x", content_type="audio/wav")


@respx.mock
async def test_no_speech_detected_raises():
    respx.post(TRANSCRIPTIONS).mock(return_value=httpx.Response(200, json={"text": "   "}))
    with pytest.raises(TranscriptionError):
        await groq.transcribe(audio=b"x", content_type="audio/wav")


@respx.mock
async def test_unparseable_response_raises():
    respx.post(TRANSCRIPTIONS).mock(return_value=httpx.Response(200, text="not json"))
    with pytest.raises(TranscriptionError):
        await groq.transcribe(audio=b"x", content_type="video/mp4")
