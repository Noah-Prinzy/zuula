"""AnalysisProvider: the interface between the submission pipeline (app/worker/pipeline.py)
and whatever actually produces a verdict. P2 shipped only a stub; P4 replaces it with
`GroqAnalysisProvider` behind the same interface, picked by ANALYSIS_PROVIDER /
ANALYSIS_PROVIDER_REGION exactly as before — sending submissions to a hosted LLM outside
Uganda is still an open §10.1 data-protection question (see docs/zuula_state.md, ADR 0001)
that Groq's hosted inference doesn't resolve either way, so the switch stays a switch rather
than a hardcoded default.

GroqAnalysisProvider orchestrates independent pieces, each its own module/provider so every
one is swappable and independently testable — this is where §4.1's Core AI/ML Engine
components (LLM Verification Module, Source Verification Engine, Explanation Generator) live,
composed back into one claim-level AnalysisResult:

1. **Embed + retrieve locally** (app/providers/embedding.py + app/providers/vector_db.py):
   embed the claim locally (multilingual — see embedding.py), then look up the nearest
   existing reports through a VectorDbProvider (pgvector by default — §4.2/§4.1 Layer 4 also
   names Pinecone, available as an alternative, see vector_db.py). This one lookup serves two
   purposes, split by how close the nearest match is (see docs/zuula_state.md, ADR 0004):
   - **Dedupe**: a match within DEDUPE_MAX_COSINE_DISTANCE is reused outright — no Tavily
     search, no Groq call — which is what keeps a viral claim (even retranslated or reworded)
     from costing anything the second time it's submitted.
   - **Local-evidence retrieval**: looser matches, within LOCAL_EVIDENCE_MAX_COSINE_DISTANCE,
     aren't close enough to reuse but are close enough to be useful grounding — Zuula's own
     verified corpus, not the open web, retrieved before the explanation step below rather
     than replacing it (_augment_with_local_evidence).
2. Otherwise (or alongside local evidence, when found), the **Source Verification Engine**
   (app/providers/source_verification.py) gathers live web evidence for the claim (one Tavily
   search, free tier, restricted to the admin-managed trusted-source registry when it has
   enough to offer), then the **Explanation Generator** (app/providers/explanation.py) turns
   the combined evidence into the verdict/claims/citations/summary shape in one Groq chat
   completion (GROQ_MODEL, free tier) — claim extraction and reasoning in the same call, not
   an agent loop, and no Claude/Anthropic calls anywhere in this engine, per the P4 cost
   constraint (free-tier Groq only). Exactly one Tavily search and one Groq call per claim
   either way: local-evidence retrieval is a free local lookup already paid for by the embed
   step above, not an extra round of either.
3. For text content, an in-process AI-generated-text signal
   (app/providers/ai_text_detector.py) is appended to ai_signals.
4. For image content, two more AI Content Detection Module signals are appended from the
   submission's raw bytes, passed in as `media` (app/worker/pipeline.py reads them from
   object storage for image submissions only): a metadata tampering check
   (app/providers/metadata_integrity.py, EXIF inconsistencies + a SHA-256 content hash, no
   model) and a basic AI-generated-image signal from a pretrained classifier
   (app/providers/deepfake_detector.py).

Deepfake-specific forensics (face-swap/lip-sync detection, trained on FaceForensics++-style
data) are out of scope — no labelled corpus, no GPU budget. deepfake_detector.py's signal is a
basic "does this look AI-generated" classifier, not that.
"""

import logging
import zlib
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AnalysisSettings, get_analysis_settings
from app.db.models import FactCheckReport
from app.db.sample_data.fact_checks import SAMPLE_REPORTS
from app.providers.ai_text_detector import AiTextDetector, get_ai_text_detector
from app.providers.deepfake_detector import DeepfakeDetector, get_deepfake_detector
from app.providers.embedding import (
    EmbeddingError,
    EmbeddingProvider,
    get_embedding_provider,
)
from app.providers.explanation import (
    ChatModel,
    Explanation,
    GroqError,
    GroqExplanationGenerator,
)
from app.providers.metadata_integrity import (
    MetadataTamperingDetector,
    get_metadata_tampering_detector,
)
from app.providers.source_verification import (
    EvidenceBundle,
    SourceVerifier,
    TavilySourceVerifier,
)
from app.providers.tavily import TavilyResult
from app.providers.vector_db import VectorDbProvider, VectorMatch, get_vector_db_provider
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
        self,
        *,
        db: AsyncSession,
        content_type: str,
        text: str,
        language: str,
        media: bytes | None = None,
    ) -> AnalysisResult:
        """Given the submission's content, produce the analysis half of a FactCheckReport
        (everything but the identity/timing/community fields the pipeline fills in itself).
        `db` is the pipeline's own session — GroqAnalysisProvider's dedupe check reads
        through it; the stub ignores it. `media` is the raw uploaded bytes for an image
        submission (None otherwise, and ignored by the stub)."""
        ...


class StubAnalysisProvider:
    """P2 stand-in: deterministically maps an input to one of the existing sample reports'
    analysis (verdict, claims, citations, ...) — the shape a real provider's output would
    have, without doing any real analysis. The same (content_type, text) always maps to the
    same sample (crc32, not Python's randomized str hash, so it's stable across processes —
    the pipeline runs in a separate worker process from whatever calls it), so demoing the
    same input twice gives a stable result."""

    async def analyze(
        self,
        *,
        db: AsyncSession,
        content_type: str,
        text: str,
        language: str,
        media: bytes | None = None,
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
        metadata_tampering_detector: MetadataTamperingDetector,
        deepfake_detector: DeepfakeDetector,
        vector_db: VectorDbProvider,
        source_verifier: SourceVerifier,
        explanation_generator: GroqExplanationGenerator,
        dedupe_max_cosine_distance: float,
        local_evidence_max_cosine_distance: float = 0.3,
        local_evidence_limit: int = 3,
    ):
        self._embedder = embedder
        self._ai_text_detector = ai_text_detector
        self._metadata_tampering_detector = metadata_tampering_detector
        self._deepfake_detector = deepfake_detector
        self._vector_db = vector_db
        self._source_verifier = source_verifier
        self._explanation_generator = explanation_generator
        self._dedupe_max_distance = dedupe_max_cosine_distance
        self._local_evidence_max_distance = local_evidence_max_cosine_distance
        self._local_evidence_limit = local_evidence_limit

    async def analyze(
        self,
        *,
        db: AsyncSession,
        content_type: str,
        text: str,
        language: str,
        media: bytes | None = None,
    ) -> AnalysisResult:
        embedding = await self._embed(text) if text.strip() else None
        local_matches: list[VectorMatch] = []

        if embedding is not None:
            local_matches = await self._vector_db.find_similar(
                db, embedding, limit=self._local_evidence_limit
            )
            if local_matches and local_matches[0].distance <= self._dedupe_max_distance:
                reused = await self._reuse_report(db, local_matches[0], embedding)
                if reused is not None:
                    return reused

        evidence = await self._source_verifier.gather_evidence(db, text)
        if local_matches:
            evidence = await self._augment_with_local_evidence(db, local_matches, evidence)
        explanation = await self._explanation_generator.generate(
            content_type=content_type, text=text, evidence=evidence
        )
        result = _result_from_explanation(explanation)
        result.embedding = embedding

        if content_type == "text":
            signal = self._ai_text_detector.detect(text)
            if signal is not None:
                result.ai_signals = [*result.ai_signals, signal]
        elif content_type == "image" and media:
            for detector in (self._metadata_tampering_detector, self._deepfake_detector):
                signal = detector.detect(media)
                if signal is not None:
                    result.ai_signals = [*result.ai_signals, signal]
        return result

    async def _embed(self, text: str) -> list[float] | None:
        """No vector (so no dedupe and no local evidence) rather than a failed check when the
        hosted embedding model is down."""
        try:
            return await self._embedder.embed(text)
        except EmbeddingError:
            logger.warning("Embedding failed; checking without the duplicate search")
            return None

    async def _reuse_report(
        self, db: AsyncSession, match: VectorMatch, embedding: list[float]
    ) -> AnalysisResult | None:
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

    async def _augment_with_local_evidence(
        self, db: AsyncSession, matches: list[VectorMatch], evidence: EvidenceBundle
    ) -> EvidenceBundle:
        """Prepend up to `_local_evidence_limit` already-verified reports from Zuula's own
        corpus to `evidence.sources`, ahead of the live Tavily results it already carries —
        the local half of this engine's retrieval (docs/zuula_state.md, ADR 0004).
        `matches` is the same vector-DB lookup `analyze` already made for the dedupe check,
        so this costs nothing extra beyond resolving each match's report row."""
        local_sources: list[TavilyResult] = []
        for match in matches:
            if match.distance <= self._dedupe_max_distance:
                continue  # close enough that analyze() already reused it outright
            if match.distance > self._local_evidence_max_distance:
                continue  # too distant to be useful grounding
            report = await db.get(FactCheckReport, match.report_id)
            if report is None:
                continue
            source = _local_evidence_source(report)
            if source is not None:
                local_sources.append(source)
        if not local_sources:
            return evidence
        return EvidenceBundle(
            sources=[*local_sources, *evidence.sources],
            trusted_domains=evidence.trusted_domains,
            local_evidence_count=len(local_sources),
        )


def _local_evidence_source(report: FactCheckReport) -> TavilyResult | None:
    """A local-evidence TavilyResult for `report`, cited to its own source rather than
    Zuula's report page — the original fact-check (e.g. the AFP article) is the citable
    authority; `report.citations[0]` is that source when the report has one (a prior
    AnalysisResult always does), falling back to the submission's own source_url."""
    url: str | None = None
    if report.citations:
        first = report.citations[0]
        if isinstance(first, dict):
            url = first.get("url")
    url = url or report.source_url
    if not url:
        return None
    return TavilyResult(
        title=report.title,
        url=url,
        snippet=report.summary[:500],
        published_at=report.checked_at.date().isoformat() if report.checked_at else None,
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


def fallback_models(settings: AnalysisSettings) -> tuple[ChatModel, ...]:
    """The verdict's fallbacks after Groq (Milestone D3): every model named in GEMINI_MODEL,
    then in OPENROUTER_MODEL (comma-separated), each provider only when its key is set."""
    providers = (
        ("Gemini", settings.gemini_api_url, settings.gemini_api_key, settings.gemini_model),
        (
            "OpenRouter",
            settings.openrouter_api_url,
            settings.openrouter_api_key,
            settings.openrouter_model,
        ),
    )
    return tuple(
        ChatModel(name=name, api_url=url, api_key=key, model=model.strip())
        for name, url, key, models in providers
        if key
        for model in models.split(",")
        if model.strip()
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
        metadata_tampering_detector=get_metadata_tampering_detector(),
        deepfake_detector=get_deepfake_detector(),
        vector_db=get_vector_db_provider(),
        source_verifier=TavilySourceVerifier(
            tavily_api_key=settings.tavily_api_key,
            tavily_api_url=settings.tavily_api_url,
            exa_api_key=settings.exa_api_key,
            exa_api_url=settings.exa_api_url,
        ),
        explanation_generator=GroqExplanationGenerator(
            groq_api_key=settings.groq_api_key,
            groq_api_url=settings.groq_api_url,
            groq_model=settings.groq_model,
            fallbacks=fallback_models(settings),
        ),
        dedupe_max_cosine_distance=settings.dedupe_max_cosine_distance,
        local_evidence_max_cosine_distance=settings.local_evidence_max_cosine_distance,
        local_evidence_limit=settings.local_evidence_limit,
    )
