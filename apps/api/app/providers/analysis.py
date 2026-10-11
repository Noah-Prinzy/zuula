"""AnalysisProvider: the interface between the submission pipeline (app/worker/pipeline.py)
and whatever actually produces a verdict. P2 shipped only a stub; P4 replaces it with
`GroqAnalysisProvider` behind the same interface, picked by ANALYSIS_PROVIDER /
ANALYSIS_PROVIDER_REGION exactly as before — sending submissions to a hosted LLM outside
Uganda is still an open §10.1 data-protection question (see docs/adr/0001-api-architecture.md)
that Groq's hosted inference doesn't resolve either way, so the switch stays a switch rather
than a hardcoded default.

GroqAnalysisProvider orchestrates independent pieces, each its own module/provider so every
one is swappable and independently testable — this is where §4.1's Core AI/ML Engine
components (LLM Verification Module, Source Verification Engine, Explanation Generator) live,
composed back into one claim-level AnalysisResult:

1. **Dedupe** (app/providers/embedding.py + app/providers/vector_db.py): embed the claim
   locally, then look for a near-duplicate existing report through a VectorDbProvider
   (pgvector by default — §4.2/§4.1 Layer 4 also names Pinecone, available as an alternative,
   see vector_db.py). A close match is reused outright — no Tavily search, no Groq call —
   which is what keeps a viral claim from costing anything the second time it's submitted.
2. Otherwise, the **Source Verification Engine** (app/providers/source_verification.py)
   gathers web evidence for the claim (one Tavily search, free tier, restricted to the
   admin-managed trusted-source registry when it has enough to offer), then the
   **Explanation Generator** (app/providers/explanation.py) turns that evidence into the
   verdict/claims/citations/summary shape in one Groq chat completion (Llama 3.3 70B, free
   tier) — claim extraction and reasoning in the same call, not an agent loop, and no
   Claude/Anthropic calls anywhere in this engine, per the P4 cost constraint (free-tier Groq
   only).
3. For text content, an in-process AI-generated-text signal
   (app/providers/ai_text_detector.py) is appended to ai_signals.

Deepfake detection (an ai_signals entry for image/video) is explicitly out of scope: Reality
Defender's free tier (50/month) doesn't make it worth building for v1. ai_signals simply has
no such entry yet — there's nothing half-built to find here.
"""

import logging
import zlib
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_analysis_settings
from app.db.models import FactCheckReport
from app.db.sample_data.fact_checks import SAMPLE_REPORTS
from app.providers.ai_text_detector import AiTextDetector, get_ai_text_detector
from app.providers.embedding import EmbeddingProvider, get_embedding_provider
from app.providers.explanation import (
    Explanation,
    GroqError,
    GroqExplanationGenerator,
)
from app.providers.source_verification import SourceVerifier, TavilySourceVerifier
from app.providers.vector_db import VectorDbProvider, get_vector_db_provider
from app.schemas.fact_check import AISignal, Citation, Claim

logger = logging.getLogger("zuula.providers.analysis")

__all__ = [
    "AnalysisProvider",
    "AnalysisResult",
    "GroqAnalysisProvider",
    "GroqError",
    "StubAnalysisProvider",
    "get_analysis_provider",
]


@dataclass
class AnalysisResult:
    title: str
    verdict: str
    confidence: int
    summary: str
    category: str
    what_is_false: list[str] = field(default_factory=list)
    what_is_true: list[str] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    ai_signals: list[AISignal] = field(default_factory=list)
    # The claim's own embedding (app/providers/embedding.py), persisted on the new
    # FactCheckReport row so the *next* near-duplicate claim finds this one. None when the
    # text was empty, or EMBEDDING_PROVIDER produced nothing.
    embedding: list[float] | None = None


class AnalysisProvider(Protocol):
    async def analyze(
        self, *, db: AsyncSession, content_type: str, text: str, language: str
    ) -> AnalysisResult:
        """Given the submission's content, produce the analysis half of a FactCheckReport
        (everything but the identity/timing/community fields the pipeline fills in itself).
        `db` is the pipeline's own session — GroqAnalysisProvider's dedupe check reads
        through it; the stub ignores it."""
        ...


class StubAnalysisProvider:
    """P2 stand-in: deterministically maps an input to one of the existing sample reports'
    analysis (verdict, claims, citations, ...) — the shape a real provider's output would
    have, without doing any real analysis. The same (content_type, text) always maps to the
    same sample (crc32, not Python's randomized str hash, so it's stable across processes —
    the pipeline runs in a separate worker process from whatever calls it), so demoing the
    same input twice gives a stable result."""

    async def analyze(
        self, *, db: AsyncSession, content_type: str, text: str, language: str
    ) -> AnalysisResult:
        digest = zlib.crc32(f"{content_type}:{text}".encode())
        sample = SAMPLE_REPORTS[digest % len(SAMPLE_REPORTS)]
        return AnalysisResult(
            title=sample.title,
            verdict=sample.verdict,
            confidence=sample.confidence,
            summary=sample.summary,
            category=sample.category,
            what_is_false=sample.what_is_false,
            what_is_true=sample.what_is_true,
            claims=sample.claims,
            citations=sample.citations,
            ai_signals=sample.ai_signals,
        )


class GroqAnalysisProvider:
    def __init__(
        self,
        *,
        embedder: EmbeddingProvider,
        ai_text_detector: AiTextDetector,
        vector_db: VectorDbProvider,
        source_verifier: SourceVerifier,
        explanation_generator: GroqExplanationGenerator,
        dedupe_max_cosine_distance: float,
    ):
        self._embedder = embedder
        self._ai_text_detector = ai_text_detector
        self._vector_db = vector_db
        self._source_verifier = source_verifier
        self._explanation_generator = explanation_generator
        self._dedupe_max_distance = dedupe_max_cosine_distance

    async def analyze(
        self, *, db: AsyncSession, content_type: str, text: str, language: str
    ) -> AnalysisResult:
        embedding = self._embedder.embed(text) if text.strip() else None

        if embedding is not None:
            reused = await self._reuse_if_duplicate(db, embedding)
            if reused is not None:
                return reused

        evidence = await self._source_verifier.gather_evidence(db, text)
        explanation = await self._explanation_generator.generate(
            content_type=content_type, text=text, evidence=evidence
        )
        result = _result_from_explanation(explanation)
        result.embedding = embedding

        if content_type == "text":
            signal = self._ai_text_detector.detect(text)
            if signal is not None:
                result.ai_signals = [*result.ai_signals, signal]
        return result

    async def _reuse_if_duplicate(
        self, db: AsyncSession, embedding: list[float]
    ) -> AnalysisResult | None:
        match = await self._vector_db.find_nearest(db, embedding)
        if match is None or match.distance > self._dedupe_max_distance:
            return None
        report = await db.get(FactCheckReport, match.report_id)
        if report is None:
            return None
        logger.info(
            "Reusing fact_check_reports %s for a near-duplicate claim (cosine distance %.4f)",
            report.id,
            match.distance,
        )
        return AnalysisResult(
            title=report.title,
            verdict=report.verdict,
            confidence=report.confidence,
            summary=report.summary,
            category=report.category,
            what_is_false=list(report.what_is_false),
            what_is_true=list(report.what_is_true),
            claims=[Claim.model_validate(c) for c in report.claims],
            citations=[Citation.model_validate(c) for c in report.citations],
            ai_signals=[AISignal.model_validate(a) for a in report.ai_signals],
            embedding=embedding,
        )


def _result_from_explanation(explanation: Explanation) -> AnalysisResult:
    return AnalysisResult(
        title=explanation.title,
        verdict=explanation.verdict,
        confidence=explanation.confidence,
        summary=explanation.summary,
        category=explanation.category,
        what_is_false=explanation.what_is_false,
        what_is_true=explanation.what_is_true,
        claims=explanation.claims,
        citations=explanation.citations,
    )


def get_analysis_provider() -> AnalysisProvider:
    """ANALYSIS_PROVIDER: `groq`, `stub`, or empty for Groq when GROQ_API_KEY is set and the
    stub otherwise (the same real-when-configured rule as app/providers/language.py)."""
    settings = get_analysis_settings()
    choice = settings.analysis_provider.strip().lower()
    if choice not in ("", "stub", "groq"):
        raise NotImplementedError(
            f"Unknown ANALYSIS_PROVIDER '{settings.analysis_provider}' — use 'groq' or 'stub'."
        )
    if choice == "stub" or (choice == "" and not settings.groq_api_key):
        return StubAnalysisProvider()
    if not settings.groq_api_key:
        raise NotImplementedError("ANALYSIS_PROVIDER=groq needs GROQ_API_KEY.")
    if not settings.tavily_api_key:
        raise NotImplementedError("ANALYSIS_PROVIDER=groq needs TAVILY_API_KEY.")
    return GroqAnalysisProvider(
        embedder=get_embedding_provider(),
        ai_text_detector=get_ai_text_detector(),
        vector_db=get_vector_db_provider(),
        source_verifier=TavilySourceVerifier(
            tavily_api_key=settings.tavily_api_key, tavily_api_url=settings.tavily_api_url
        ),
        explanation_generator=GroqExplanationGenerator(
            groq_api_key=settings.groq_api_key,
            groq_api_url=settings.groq_api_url,
            groq_model=settings.groq_model,
        ),
        dedupe_max_cosine_distance=settings.dedupe_max_cosine_distance,
    )
