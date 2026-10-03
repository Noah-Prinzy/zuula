"""TranscriptionProvider: the `transcribe` step for audio/video submissions
(app/worker/pipeline.py). `GroqWhisperProvider` calls Groq's hosted Whisper (OpenAI-compatible
`/audio/transcriptions` endpoint, free tier: 2,000 requests/day) — same real-when-configured
pattern as app/providers/language.py's SunbirdLanguageProvider: picked by GROQ_API_KEY, raises
NotImplementedError on an unknown TRANSCRIPTION_PROVIDER value.

This only transcribes (same language in, same language out); it doesn't translate to English
the way Whisper's `/audio/translations` endpoint would. Media submissions have no `language`
step (ADR 0003 covers text/url/article only), so the transcript is handed to `claims` exactly
as `_to_pivot()` already treats any non-English, non-"other" text it can't place: passed
through untranslated.
"""

from typing import Protocol

import httpx

from app.core.config import get_analysis_settings

# Whisper's accepted upload extensions, by the submission's declared MIME subtype. Anything
# else falls back to "webm", the extension least likely to be flatly rejected before Whisper
# even looks at the bytes.
_EXTENSIONS: dict[str, str] = {
    "mpeg": "mp3",
    "mp3": "mp3",
    "mp4": "mp4",
    "m4a": "m4a",
    "wav": "wav",
    "x-wav": "wav",
    "webm": "webm",
    "ogg": "ogg",
}


class TranscriptionError(Exception):
    """Transcription failed; its message is shown to the submitter as-is
    (app/worker/pipeline.py's failure path), so it stays free of response-body detail."""


class TranscriptionProvider(Protocol):
    async def transcribe(self, *, audio: bytes, content_type: str) -> str:
        """Transcribe `audio` (the submission's media bytes) into text, in whatever language
        it's spoken in."""
        ...


class StubTranscriptionProvider:
    """Dev/test stand-in: no network, deterministic. Tagged the same way
    StubLanguageProvider.translate() tags its output, so a stub transcript can't be mistaken
    for a real one."""

    async def transcribe(self, *, audio: bytes, content_type: str) -> str:
        return f"[stub-transcription {content_type}] {len(audio)} bytes of media"


class GroqWhisperProvider:
    def __init__(self, *, api_url: str, api_key: str, model: str, timeout: float = 60.0):
        self._url = f"{api_url.rstrip('/')}/audio/transcriptions"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._model = model
        self._timeout = timeout

    async def transcribe(self, *, audio: bytes, content_type: str) -> str:
        extension = _EXTENSIONS.get(content_type.rpartition("/")[2].lower(), "webm")
        files = {"file": (f"upload.{extension}", audio, content_type or "application/octet-stream")}
        data = {"model": self._model, "response_format": "json"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    self._url, headers=self._headers, data=data, files=files
                )
        except httpx.HTTPError as exc:
            raise TranscriptionError("We couldn't transcribe that audio or video.") from exc
        # Never include the response body: it could echo audio-derived text into logs.
        if response.status_code >= 400:
            raise TranscriptionError("We couldn't transcribe that audio or video.")
        try:
            text = response.json()["text"]
        except (ValueError, KeyError) as exc:
            raise TranscriptionError("We couldn't transcribe that audio or video.") from exc
        if not isinstance(text, str) or not text.strip():
            raise TranscriptionError("We couldn't make out any speech in that audio or video.")
        return text.strip()


def get_transcription_provider() -> TranscriptionProvider:
    """TRANSCRIPTION_PROVIDER: `groq`, `stub`, or empty for Groq when GROQ_API_KEY is set and
    the stub otherwise."""
    settings = get_analysis_settings()
    choice = settings.transcription_provider.strip().lower()
    if choice not in ("", "stub", "groq"):
        raise NotImplementedError(
            f"Unknown TRANSCRIPTION_PROVIDER '{settings.transcription_provider}': use 'groq' "
            "or 'stub'."
        )
    if choice == "stub" or (choice == "" and not settings.groq_api_key):
        return StubTranscriptionProvider()
    if not settings.groq_api_key:
        raise NotImplementedError("TRANSCRIPTION_PROVIDER=groq needs GROQ_API_KEY.")
    return GroqWhisperProvider(
        api_url=settings.groq_api_url,
        api_key=settings.groq_api_key,
        model=settings.groq_whisper_model,
    )
