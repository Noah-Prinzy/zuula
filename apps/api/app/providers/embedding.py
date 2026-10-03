"""EmbeddingProvider: turns a claim's text into the fixed-length vector
`app.providers.analysis.GroqAnalysisProvider` uses for the dedupe check — a pgvector
nearest-neighbor search against `fact_check_reports.embedding` that reuses a close match's
report instead of spending a Tavily search and a Groq generation on the same viral claim
again.

`SentenceTransformerEmbeddingProvider` runs `all-MiniLM-L6-v2` locally on CPU
(sentence-transformers; no API key, no hosted endpoint — free). It needs a real model
download, so `EMBEDDING_PROVIDER` defaults to `stub` rather than real-when-configured: there's
no credential to gate on the way there is for Groq/Tavily, and the test suite must never try
to pull a model over the network. The model is loaded once per process and cached
(_load_model), not once per call — it's too slow to reload for every submission.

EMBEDDING_DIMENSIONS (384) must match all-MiniLM-L6-v2's output size: it's also the pgvector
column's fixed dimension (migrations/versions/0004_embedding_dimensions.py). Changing the
model means a new migration to match.
"""

import zlib
from functools import lru_cache
from typing import Protocol

from app.core.config import get_analysis_settings

EMBEDDING_DIMENSIONS = 384


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]:
        """A unit-length vector of length EMBEDDING_DIMENSIONS representing `text`."""
        ...


class StubEmbeddingProvider:
    """Dev/test stand-in: no model download, deterministic, no network. A crude
    hashed-bag-of-words vector — nowhere near a real sentence embedding, but, like
    StubLanguageProvider's marker-word matching, good enough to tell test fixtures apart:
    near-identical text hashes to a near-identical vector, unrelated text doesn't."""

    def embed(self, text: str) -> list[float]:
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

    def embed(self, text: str) -> list[float]:
        model = _load_model(self._model_name)
        return model.encode(text, normalize_embeddings=True).tolist()


@lru_cache
def _load_model(model_name: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name, device="cpu")


def get_embedding_provider() -> EmbeddingProvider:
    """EMBEDDING_PROVIDER: `sentence-transformers` for the real local model, `stub` (the
    default) otherwise."""
    settings = get_analysis_settings()
    choice = settings.embedding_provider.strip().lower()
    if choice not in ("stub", "sentence-transformers"):
        raise NotImplementedError(
            f"Unknown EMBEDDING_PROVIDER '{settings.embedding_provider}': use "
            "'sentence-transformers' or 'stub'."
        )
    if choice == "stub":
        return StubEmbeddingProvider()
    return SentenceTransformerEmbeddingProvider(settings.embedding_model)
