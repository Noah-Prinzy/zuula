"""EmbeddingProvider: turns a claim's text into the fixed-length vector
`app.providers.analysis.GroqAnalysisProvider` uses for two things, both pgvector
nearest-neighbor searches against `fact_check_reports.embedding`: the dedupe check (reuse an
existing report outright for a near-identical claim) and the local-evidence retrieval step
(surface related, already-verified reports as grounding for the Explanation Generator — see
docs/zuula_state.md, ADR 0004). Neither spends a Tavily search or a Groq call on work
already done.

`SentenceTransformerEmbeddingProvider` runs `paraphrase-multilingual-MiniLM-L12-v2` locally on
CPU (sentence-transformers; no API key, no hosted endpoint — free), chosen over the
English-only `all-MiniLM-L6-v2` it replaced so a non-English resubmission (Luganda, Acholi,
Swahili, ...) of an already-checked claim still matches it. It needs a real model download,
so `EMBEDDING_PROVIDER` defaults to `stub` rather than real-when-configured: there's no
credential to gate on the way there is for Groq/Tavily, and the test suite must never try to
pull a model over the network. The model is loaded once per process and cached (_load_model),
not once per call — it's too slow to reload for every submission.

Production (Milestone D7) uses Google's `gemini-embedding-001` instead
(`GeminiEmbeddingProvider`), asked for 384 dimensions so the pgvector column stays as it is.
Measured on 29 Oct 2026: the local model needs about 615 MB in ONNX form (fastembed), more
than Render's whole 512 MB; the same model on Hugging Face's Inference API
(`HuggingFaceEmbeddingProvider`, kept as an option) needs paid credit; and the local model
barely relates Luganda to English (the same claim 0.72 apart, unrelated claims 0.88), where
Gemini puts them 0.12 apart. Gemini's distances run on a narrower scale, so the dedupe and
local-evidence thresholds were recalibrated with it (app/core/config.py). Vectors from
different models aren't comparable: switching models means re-embedding every stored report
(app/db/backfill_embeddings.py --all). `embed()` is async because the hosted models are a
network call and checks run on the API's own event loop on Render (JOB_RUNNER=inline); the
local model runs in a thread for the same reason.

EMBEDDING_DIMENSIONS (384) must match the configured model's output size: it's also the
pgvector column's fixed dimension (migrations/versions/0004_embedding_dimensions.py).
paraphrase-multilingual-MiniLM-L12-v2 happens to share all-MiniLM-L6-v2's 384 dims, so this
model swap needed no new migration; a future model with a different output size would.
"""

import asyncio
import logging
import zlib
from functools import lru_cache
from typing import Protocol

import httpx

from app.core.config import get_analysis_settings

logger = logging.getLogger("zuula.providers.embedding")

EMBEDDING_DIMENSIONS = 384


class EmbeddingError(Exception):
    """The hosted model didn't answer with a vector; the check goes on without one (no
    dedupe, no local evidence), as with an empty text."""


class EmbeddingProvider(Protocol):
    async def embed(self, text: str) -> list[float]:
        """A unit-length vector of length EMBEDDING_DIMENSIONS representing `text`."""
        ...


class StubEmbeddingProvider:
    """Dev/test stand-in: no model download, deterministic, no network. A crude
    hashed-bag-of-words vector — nowhere near a real sentence embedding, but, like
    StubLanguageProvider's marker-word matching, good enough to tell test fixtures apart:
    near-identical text hashes to a near-identical vector, unrelated text doesn't."""

    async def embed(self, text: str) -> list[float]:
        return stub_embedding(text)


def stub_embedding(text: str) -> list[float]:
    """StubEmbeddingProvider's vector, synchronously (tests build expected vectors with it)."""
    # zlib.crc32, not Python's randomized str hash, so the same text hashes to the same
    # vector across processes (the worker runs in its own process) — same reasoning as
    # StubAnalysisProvider's digest.
    vector = [0.0] * EMBEDDING_DIMENSIONS
    words = text.lower().split()
    if not words:
        return vector
    for word in words:
        digest = zlib.crc32(word.encode())
        vector[digest % EMBEDDING_DIMENSIONS] += 1.0 if digest % 2 == 0 else -1.0
    norm = sum(v * v for v in vector) ** 0.5
    return [v / norm for v in vector] if norm else vector


class SentenceTransformerEmbeddingProvider:
    def __init__(self, model_name: str):
        self._model_name = model_name

    async def embed(self, text: str) -> list[float]:
        def encode() -> list[float]:
            model = _load_model(self._model_name)
            return model.encode(text, normalize_embeddings=True).tolist()

        return await asyncio.to_thread(encode)


class GeminiEmbeddingProvider:
    """Google's embedding model through the Gemini API key the verdict fallback already
    uses. SEMANTIC_SIMILARITY is the task type for comparing claims with each other."""

    def __init__(self, *, api_url: str, api_key: str, model_name: str, timeout: float = 20.0):
        self._url = f"{api_url.rstrip('/')}/models/{model_name}:embedContent"
        self._headers = {"x-goog-api-key": api_key}
        self._timeout = timeout

    async def embed(self, text: str) -> list[float]:
        from app.services import provider_health  # Admin → System health (Milestone D6)

        try:
            vector = await self._request(text)
        except EmbeddingError as exc:
            await provider_health.record("Gemini embeddings", ok=False, error=str(exc))
            raise
        await provider_health.record("Gemini embeddings", ok=True)
        return vector

    async def _request(self, text: str) -> list[float]:
        payload = {
            "content": {"parts": [{"text": text}]},
            "taskType": "SEMANTIC_SIMILARITY",
            "outputDimensionality": EMBEDDING_DIMENSIONS,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(self._url, json=payload, headers=self._headers)
        except httpx.HTTPError as exc:
            raise EmbeddingError(type(exc).__name__) from exc
        # Never include the body: it could echo the submission back.
        if response.status_code >= 400:
            raise EmbeddingError(f"HTTP {response.status_code}")
        try:
            vector = [float(v) for v in response.json()["embedding"]["values"]]
        except (ValueError, TypeError, KeyError) as exc:
            raise EmbeddingError("Unexpected answer") from exc
        return _unit(vector)


class HuggingFaceEmbeddingProvider:
    """The same model on Hugging Face's Inference API (`hf-inference`, its feature-extraction
    pipeline), with a read token. One short call per check."""

    def __init__(self, *, api_url: str, token: str, model_name: str, timeout: float = 20.0):
        self._url = f"{api_url.rstrip('/')}/models/{model_name}/pipeline/feature-extraction"
        self._headers = {"Authorization": f"Bearer {token}"}
        self._timeout = timeout

    async def embed(self, text: str) -> list[float]:
        from app.services import provider_health  # Admin → System health (Milestone D6)

        try:
            vector = await self._request(text)
        except EmbeddingError as exc:
            await provider_health.record("Hugging Face", ok=False, error=str(exc))
            raise
        await provider_health.record("Hugging Face", ok=True)
        return vector

    async def _request(self, text: str) -> list[float]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    self._url, json={"inputs": text}, headers=self._headers
                )
        except httpx.HTTPError as exc:
            raise EmbeddingError(type(exc).__name__) from exc
        # Never include the body: it could echo the submission back.
        if response.status_code >= 400:
            raise EmbeddingError(f"HTTP {response.status_code}")
        try:
            vector = _pooled(response.json())
        except (ValueError, TypeError) as exc:
            raise EmbeddingError("Unexpected answer") from exc
        return _unit(vector)


def _unit(vector: list[float]) -> list[float]:
    """Unit length (Gemini only normalises its full-size vectors), and the column's size."""
    if len(vector) != EMBEDDING_DIMENSIONS:
        raise EmbeddingError(f"{len(vector)} dimensions, not {EMBEDDING_DIMENSIONS}")
    norm = sum(v * v for v in vector) ** 0.5
    return [v / norm for v in vector] if norm else vector


def _pooled(body) -> list[float]:
    """The sentence vector: the pipeline answers with it directly, or (for some deployments)
    with one vector per token, which sentence-transformers would mean-pool."""
    while isinstance(body, list) and body and isinstance(body[0], list):
        if body[0] and isinstance(body[0][0], list):
            body = body[0]  # a batch of one
            continue
        return [sum(column) / len(body) for column in zip(*body, strict=True)]
    if not isinstance(body, list) or not all(isinstance(v, int | float) for v in body):
        raise TypeError("not a vector")
    return [float(v) for v in body]


@lru_cache
def _load_model(model_name: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name, device="cpu")


def get_embedding_provider() -> EmbeddingProvider:
    """EMBEDDING_PROVIDER: `gemini` (production; needs GEMINI_API_KEY) or `huggingface`
    (needs HF_TOKEN) for a hosted model, each falling back to the stub with a warning
    without its key; `sentence-transformers` for the local model; `stub` (the default)."""
    settings = get_analysis_settings()
    choice = settings.embedding_provider.strip().lower()
    if choice not in ("stub", "sentence-transformers", "huggingface", "gemini"):
        raise NotImplementedError(
            f"Unknown EMBEDDING_PROVIDER '{settings.embedding_provider}': use "
            "'gemini', 'huggingface', 'sentence-transformers' or 'stub'."
        )
    if choice == "gemini":
        if settings.gemini_api_key:
            return GeminiEmbeddingProvider(
                api_url=settings.gemini_native_api_url,
                api_key=settings.gemini_api_key,
                model_name=settings.gemini_embedding_model,
            )
        logger.warning("EMBEDDING_PROVIDER=gemini needs GEMINI_API_KEY; using the stub")
        return StubEmbeddingProvider()
    if choice == "huggingface":
        if settings.hf_token:
            return HuggingFaceEmbeddingProvider(
                api_url=settings.hf_api_url,
                token=settings.hf_token,
                model_name=settings.embedding_model,
            )
        logger.warning("EMBEDDING_PROVIDER=huggingface needs HF_TOKEN; using the stub")
        return StubEmbeddingProvider()
    if choice == "stub":
        return StubEmbeddingProvider()
    return SentenceTransformerEmbeddingProvider(settings.embedding_model)
