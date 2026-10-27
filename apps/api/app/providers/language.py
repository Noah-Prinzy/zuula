"""LanguageProvider: the interface between the submission pipeline and whatever identifies
and translates the five languages Zuula supports (FR-SUBMIT-03: English, Luganda, Acholi,
Runyankole, Ateso). The real implementation is Sunbird AI (`SunbirdLanguageProvider`); the
stub stays for local dev and the tests. See docs/zuula_state.md, ADR 0003.

Two jobs, matching the pipeline's `language` step (app/worker/pipeline.py's PIPELINES,
transcribed from apps/web/lib/analysis.ts: "Identifying the language and any
code-switching") and FR-EXPLAIN-05 (explanations in the submitted content's language):

- `detect()`: which of the five languages a submission is in, plus any others it switches
  into. Only needed when the submitter picked `auto` (openapi.yaml's SubmissionInput.language:
  "A LocaleCode, or `auto` to detect"); see resolve_submission_language().
- `translate()`: two directions. Inbound, the submission's text into PIVOT_LANGUAGE for the
  claims/sources/ai steps, since trusted sources and the verdict engine work in English.
  Outbound, the finished explanation from PIVOT_LANGUAGE back into the submission's language.

The pipeline calls both (app/worker/pipeline.py's `_resolve_language()`, `_to_pivot()` and
`_explain_in()`).
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from app.core.config import get_language_settings

logger = logging.getLogger("zuula.providers.language")

# LocaleCode -> display name. Mirrors apps/web/lib/locales.ts's LOCALES exactly. The API
# takes codes on the way in (SubmissionInput.language) and stores display names on
# FactCheckReport.language (app/db/models/content.py), so both halves live here.
SUPPORTED_LANGUAGES: dict[str, str] = {
    "en": "English",
    "lg": "Luganda",
    "ach": "Acholi",
    "nyn": "Runyankole",
    "teo": "Ateso",
}

# Detected, but not one of the five. The pipeline can't translate it and shouldn't try.
OTHER = "other"

# What SubmissionInput.language carries when the submitter didn't pick a language.
AUTO = "auto"

# The language claim extraction, source matching and the verdict engine work in. Trusted
# sources are mostly English, and so is AnalysisProvider's stub output.
PIVOT_LANGUAGE = "en"


@dataclass
class DetectionResult:
    # A SUPPORTED_LANGUAGES code, or OTHER.
    language: str
    # 0.0-1.0: how sure the provider is about `language`. None when the provider doesn't say
    # (Sunbird's language_id returns a language only).
    confidence: float | None
    # Other supported languages the text also uses (code-switching), most-used first.
    # Never includes `language`.
    also_contains: list[str] = field(default_factory=list)


@dataclass
class TranslationResult:
    text: str
    source: str
    target: str
    # False when nothing was translated (source == target), so callers can tell a
    # pass-through from a real translation without comparing strings.
    translated: bool


class LanguageProvider(Protocol):
    async def detect(self, *, text: str) -> DetectionResult:
        """Identify which supported language `text` is in (or OTHER)."""
        ...

    async def translate(self, *, text: str, source: str, target: str) -> TranslationResult:
        """Translate `text` between two SUPPORTED_LANGUAGES codes. Raises ValueError for any
        other code, OTHER included."""
        ...


# A few common function words per language, picked so the stub can tell test fixtures
# apart. This is not a language model and won't hold up on real text: Luganda and
# Runyankole in particular share a lot of vocabulary. Sunbird replaces all of it.
_MARKERS: dict[str, frozenset[str]] = {
    "en": frozenset({"the", "and", "is", "are", "of", "to", "that", "will", "this", "with"}),
    "lg": frozenset({"nti", "era", "naye", "kubanga", "bwe", "ssente", "gavumenti", "okuva"}),
    "ach": frozenset({"ki", "pa", "ento", "pien", "tye", "dano", "gin", "lok"}),
    "nyn": frozenset({"kandi", "ahabwokuba", "kuruga", "okuruga", "reero", "mbwenu", "nibyo"}),
    "teo": frozenset({"arai", "itunga", "eong", "ijo", "kere", "ebe", "kotoma"}),
}

_WORD = re.compile(r"[^\W\d_]+")


def _check_supported(code: str) -> None:
    if code not in SUPPORTED_LANGUAGES:
        raise ValueError(
            f"Unsupported language '{code}'; expected one of {sorted(SUPPORTED_LANGUAGES)}"
        )


class StubLanguageProvider:
    """Stand-in until Sunbird: deterministic, no network.

    `detect()` counts marker words per language (_MARKERS). The language with the most hits
    wins; ties go to the earlier language in SUPPORTED_LANGUAGES order. No hits at all is
    OTHER. Other languages with hits are reported as code-switching.

    `translate()` doesn't translate. It tags the text with a visible `[stub-translation
    xx->yy]` prefix so a stub translation can't be mistaken for a real one in a demo or in a
    stored report. Same source and target returns the text unchanged."""

    async def detect(self, *, text: str) -> DetectionResult:
        words = [w.lower() for w in _WORD.findall(text)]
        hits = {code: sum(w in markers for w in words) for code, markers in _MARKERS.items()}
        total = sum(hits.values())
        if total == 0:
            return DetectionResult(language=OTHER, confidence=0.0)

        order = list(SUPPORTED_LANGUAGES)
        ranked = sorted(
            (code for code in order if hits[code]),
            key=lambda code: (-hits[code], order.index(code)),
        )
        top = ranked[0]
        return DetectionResult(
            language=top,
            confidence=round(hits[top] / total, 2),
            also_contains=ranked[1:],
        )

    async def translate(self, *, text: str, source: str, target: str) -> TranslationResult:
        _check_supported(source)
        _check_supported(target)
        if source == target:
            return TranslationResult(text=text, source=source, target=target, translated=False)
        return TranslationResult(
            text=f"[stub-translation {source}->{target}] {text}",
            source=source,
            target=target,
            translated=True,
        )


async def resolve_submission_language(requested: str, text: str, provider: LanguageProvider) -> str:
    """What the pipeline's `language` step needs to decide: the submission's language code.

    A language the submitter picked explicitly is trusted as-is (no detection call). `auto`,
    or anything that isn't a supported code, goes to detection, which may return OTHER."""
    if requested in SUPPORTED_LANGUAGES:
        return requested
    return (await provider.detect(text=text)).language


def display_name(code: str) -> str:
    """The display name FactCheckReport.language stores ("Luganda"), or "Other"."""
    return SUPPORTED_LANGUAGES.get(code, "Other")


class SunbirdError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        # The HTTP status Sunbird answered with, when it answered with an error; 429 is the
        # per-minute rate limit or the daily quota.
        self.status_code = status_code


def _retry_after(response: httpx.Response) -> str:
    """The `, retry after Ns` suffix from a 429's `details[].retry_after_seconds`, or "" when
    it isn't there. Only that number is read; the rest of the body stays out of the logs."""
    try:
        details = response.json().get("details") or []
        seconds = next(
            d["retry_after_seconds"]
            for d in details
            if isinstance(d, dict) and isinstance(d.get("retry_after_seconds"), int | float)
        )
    except (ValueError, AttributeError, StopIteration):
        return ""
    return f", retry after {int(seconds)}s"


class SunbirdLanguageProvider:
    """Sunbird AI's hosted API (https://api.sunbird.ai), bearer-token auth.

    - `detect()`: `POST /tasks/language_id` with `{"text"}`, answered with a language code.
      Sunbird reports no confidence and no code-switching, so `confidence` is None and
      `also_contains` is empty. A language outside the five (Lugbara, say) is OTHER.
    - `translate()`: `POST /tasks/translate` (the sunflower-9b LLM; it replaced
      `/tasks/nllb_translate`, which now answers 405) with `{"source_language",
      "target_language", "text"}`, answered with `output.translated_text` (and
      `output.Error` when it failed). Not `output.text`: despite the schema calling it the
      translated output, it echoes the input back. Long text is sent in chunks of whole
      sentences (_CHUNK_CHARS); see there for why.

    Being an LLM, sunflower-9b can add a trailing period to a short input, and it can
    translate named `{placeholders}` (`{name}` came back as `{erinnya}` in Luganda; numeric
    `{0}` survived). Submissions and explanations carry no placeholders, but templated text
    would need them protected before it's sent.

    Limits seen on a real key (24 Sep 2026): about 50 requests a minute and a daily quota of
    roughly 450-500 requests, both answered with HTTP 429; see _post().

    Sunbird's codes are three letters (`eng`, `lug`, …); Zuula's are the frontend's
    LocaleCodes (`en`, `lg`, …), mapped by _SUNBIRD_CODES."""

    def __init__(self, *, api_url: str, api_key: str, timeout: float = 30.0):
        self._url = api_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
        self._timeout = timeout

    async def _post(self, client: httpx.AsyncClient, path: str, payload: dict) -> dict:
        response = await client.post(f"{self._url}{path}", json=payload, headers=self._headers)
        # Never include the response body: it could echo the submission back into logs.
        if response.status_code == 429:
            raise SunbirdError(
                f"Sunbird {path} refused: rate limit or daily quota exceeded (HTTP 429"
                f"{_retry_after(response)}).",
                status_code=429,
            )
        if response.status_code >= 400:
            raise SunbirdError(
                f"Sunbird {path} failed with HTTP {response.status_code}.",
                status_code=response.status_code,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise SunbirdError(f"Sunbird {path} returned something other than JSON.") from exc

    async def detect(self, *, text: str) -> DetectionResult:
        if not text.strip():
            return DetectionResult(language=OTHER, confidence=None)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            body = await self._post(client, "/tasks/language_id", {"text": text[:_CHUNK_CHARS]})
        # The documented answer is {"language": "lug"}; accept it nested under "output" too.
        found = body.get("language") or (body.get("output") or {}).get("language") or ""
        return DetectionResult(
            language=_FROM_SUNBIRD.get(str(found).lower(), OTHER), confidence=None
        )

    async def translate(self, *, text: str, source: str, target: str) -> TranslationResult:
        _check_supported(source)
        _check_supported(target)
        if source == target or not text.strip():
            return TranslationResult(text=text, source=source, target=target, translated=False)
        parts = []
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for chunk in _chunks(text):
                body = await self._post(
                    client,
                    "/tasks/translate",
                    {
                        "source_language": _SUNBIRD_CODES[source],
                        "target_language": _SUNBIRD_CODES[target],
                        "text": chunk,
                    },
                )
                output = body.get("output") or {}
                if output.get("Error") or not isinstance(output.get("translated_text"), str):
                    raise SunbirdError("Sunbird couldn't translate the text.")
                parts.append(output["translated_text"].strip())
        return TranslationResult(
            text=" ".join(parts), source=source, target=target, translated=True
        )


# Zuula LocaleCode -> Sunbird's language code, and back.
_SUNBIRD_CODES: dict[str, str] = {
    "en": "eng",
    "lg": "lug",
    "ach": "ach",
    "nyn": "nyn",
    "teo": "teo",
}
_FROM_SUNBIRD: dict[str, str] = {v: k for k, v in _SUNBIRD_CODES.items()}

# Longest piece of text sent to Sunbird in one request. Written for NLLB's short-passage
# limit; kept for sunflower-9b because Sunbird's OpenAPI spec still states no maximum length
# for /tasks/translate, while it does document 503 for an inference timeout and 502 for empty
# model output, both likelier on one long generation. 1,000 is still an assumption, not a
# verified limit.
_CHUNK_CHARS = 1000
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")


def _chunks(text: str) -> list[str]:
    """Whole sentences packed into pieces of at most _CHUNK_CHARS; a single longer sentence
    is cut at the limit."""
    chunks: list[str] = []
    current = ""
    for sentence in (p.strip() for p in _SENTENCE_END.split(text)):
        if not sentence:
            continue
        while len(sentence) > _CHUNK_CHARS:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(sentence[:_CHUNK_CHARS])
            sentence = sentence[_CHUNK_CHARS:]
        if current and len(current) + 1 + len(sentence) > _CHUNK_CHARS:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks


def get_language_provider() -> LanguageProvider:
    """LANGUAGE_PROVIDER: `sunbird`, `stub`, or empty for Sunbird when SUNBIRD_API_KEY is set
    and the stub otherwise (the same real-when-configured rule as app/adapters/)."""
    settings = get_language_settings()
    choice = settings.language_provider.strip().lower()
    if choice not in ("", "stub", "sunbird"):
        raise NotImplementedError(
            f"Unknown LANGUAGE_PROVIDER '{settings.language_provider}': use 'sunbird' or 'stub'."
        )
    if choice == "stub" or (choice == "" and not settings.sunbird_api_key):
        return StubLanguageProvider()
    if not settings.sunbird_api_key:
        raise NotImplementedError("LANGUAGE_PROVIDER=sunbird needs SUNBIRD_API_KEY.")
    return SunbirdLanguageProvider(
        api_url=settings.sunbird_api_url, api_key=settings.sunbird_api_key
    )
