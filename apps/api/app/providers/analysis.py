"""AnalysisProvider: the interface between the submission pipeline (app/worker/pipeline.py)
and whatever actually produces a verdict. P2 shipped only a stub; P4 replaces it with
`GroqAnalysisProvider` behind the same interface, picked by ANALYSIS_PROVIDER /
ANALYSIS_PROVIDER_REGION exactly as before — sending submissions to a hosted LLM outside
Uganda is still an open §10.1 data-protection question (see docs/adr/0001-api-architecture.md)
that Groq's hosted inference doesn't resolve either way, so the switch stays a switch rather
than a hardcoded default.

GroqAnalysisProvider does, per claim, in this order:

1. Embed the claim locally (app/providers/embedding.py) and look for a near-duplicate
   existing report (pgvector cosine distance against `fact_check_reports.embedding`). A close
   match is reused outright — no Tavily search, no Groq call — which is what keeps the same
   viral claim from costing anything the second time it's submitted.
2. Otherwise, one Tavily web search for evidence (app/providers/tavily.py) and one Groq chat
   completion (Llama 3.3 70B, free tier) over the claim and that evidence, asked to return the
   verdict/claims/citations/summary shape in one JSON response — claim extraction and
   reasoning in the same call, not an agent loop. No Claude/Anthropic calls anywhere in this
   engine, per the P4 cost constraint (free-tier Groq only).
3. For text content, an in-process AI-generated-text signal (app/providers/ai_text_detector.py)
   is appended to ai_signals.

Deepfake detection (an ai_signals entry for image/video) is explicitly out of scope: Reality
Defender's free tier (50/month) doesn't make it worth building for v1. ai_signals simply has
no such entry yet — there's nothing half-built to find here.
"""

import json
import logging
import zlib
from dataclasses import dataclass, field
from typing import Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_analysis_settings
from app.db.models import FactCheckReport
from app.db.sample_data.fact_checks import SAMPLE_REPORTS
from app.providers.ai_text_detector import AiTextDetector, get_ai_text_detector
from app.providers.embedding import EmbeddingProvider, get_embedding_provider
from app.providers.tavily import TavilyResult, TavilySearchError, tavily_search
from app.schemas.common import CitationStance, ClaimAssessment, Verdict
from app.schemas.fact_check import AISignal, Citation, Claim

logger = logging.getLogger("zuula.providers.analysis")

_VERDICTS: tuple[Verdict, ...] = (
    "authentic",
    "likely-false",
    "false",
    "ai-generated",
    "unverifiable",
)
_ASSESSMENTS: tuple[ClaimAssessment, ...] = (
    "false",
    "misleading",
    "unsupported",
    "out-of-context",
    "supported",
)
_STANCES: tuple[CitationStance, ...] = ("supports", "contradicts", "context")


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
        `fact_check_reports` through it; the stub ignores it."""
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


class GroqError(Exception):
    pass


_SYSTEM_PROMPT = """\
You are Zuula's fact-checking engine for Uganda. You are given a claim (possibly an article \
or a social media post) and a numbered list of web search results. Weigh the claim against \
the evidence and reply with ONLY a JSON object, no other text, of this exact shape:

{
  "verdict": one of "authentic", "likely-false", "false", "ai-generated", "unverifiable",
  "confidence": integer 0-100,
  "title": a short, neutral title for the claim being checked,
  "summary": 1-3 sentences explaining the verdict,
  "category": a short topic category, e.g. "Health", "Politics", "Economy",
  "whatIsFalse": list of short strings naming what's false (empty if nothing is),
  "whatIsTrue": list of short strings naming what's true or confirmed (can be empty),
  "claims": list of {
    "text": a short quote or paraphrase of the specific factual claim,
    "assessment": one of "false", "misleading", "unsupported", "out-of-context", "supported",
    "reason": 1-2 sentences explaining the assessment,
    "sourceIndexes": list of integers, the 0-based indexes of the search results (below) that
      support this assessment; empty if none do
  },
  "citationStances": list of {"index": integer, "stance": one of "supports", "contradicts", \
"context"}, one entry per search result index you actually cited in "claims"
}

If there are no search results, or none are relevant, say so in "summary" and lean toward
"unverifiable" rather than guessing. Only use the search results given; never invent URLs or
sources."""


def _sources_block(sources: list[TavilyResult]) -> str:
    if not sources:
        return "No web search results were found."
    lines = [
        f"[{i}] {s.title} ({s.url}, published {s.published_at or 'date unknown'}): "
        f"{s.snippet[:500]}"
        for i, s in enumerate(sources)
    ]
    return "\n".join(lines)


def _find_span(text: str, snippet: str) -> tuple[int, int]:
    if snippet:
        start = text.find(snippet)
        if start != -1:
            return start, start + len(snippet)
    return 0, len(text)


def _coerce(value: object, allowed: tuple[str, ...], default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


class GroqAnalysisProvider:
    def __init__(
        self,
        *,
        groq_api_key: str,
        groq_api_url: str,
        groq_model: str,
        tavily_api_key: str,
        tavily_api_url: str,
        embedder: EmbeddingProvider,
        ai_text_detector: AiTextDetector,
        dedupe_max_cosine_distance: float,
        timeout: float = 30.0,
    ):
        self._groq_api_key = groq_api_key
        self._groq_url = f"{groq_api_url.rstrip('/')}/chat/completions"
        self._groq_model = groq_model
        self._tavily_api_key = tavily_api_key
        self._tavily_api_url = tavily_api_url
        self._embedder = embedder
        self._ai_text_detector = ai_text_detector
        self._dedupe_max_distance = dedupe_max_cosine_distance
        self._timeout = timeout

    async def analyze(
        self, *, db: AsyncSession, content_type: str, text: str, language: str
    ) -> AnalysisResult:
        embedding = self._embedder.embed(text) if text.strip() else None

        if embedding is not None:
            reused = await self._reuse_if_duplicate(db, embedding)
            if reused is not None:
                return reused

        try:
            sources = await tavily_search(
                api_key=self._tavily_api_key,
                api_url=self._tavily_api_url,
                query=text[:400],
                timeout=self._timeout,
            )
        except TavilySearchError:
            logger.warning("Tavily search failed; analyzing without web evidence", exc_info=True)
            sources = []

        result = await self._verdict(content_type=content_type, text=text, sources=sources)
        result.embedding = embedding

        if content_type == "text":
            signal = self._ai_text_detector.detect(text)
            if signal is not None:
                result.ai_signals = [*result.ai_signals, signal]
        return result

    async def _reuse_if_duplicate(
        self, db: AsyncSession, embedding: list[float]
    ) -> AnalysisResult | None:
        distance = FactCheckReport.embedding.cosine_distance(embedding)
        row = (
            await db.execute(
                select(FactCheckReport, distance.label("distance"))
                .where(FactCheckReport.embedding.is_not(None))
                .order_by(distance)
                .limit(1)
            )
        ).first()
        if row is None or row.distance is None or row.distance > self._dedupe_max_distance:
            return None
        report = row[0]
        logger.info(
            "Reusing fact_check_reports %s for a near-duplicate claim (cosine distance %.4f)",
            report.id,
            row.distance,
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

    async def _verdict(
        self, *, content_type: str, text: str, sources: list[TavilyResult]
    ) -> AnalysisResult:
        payload = {
            "model": self._groq_model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Content type: {content_type}\n\nSubmitted content:\n{text}\n\n"
                        f"Web search results:\n{_sources_block(sources)}"
                    ),
                },
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self._groq_api_key}"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(self._groq_url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise GroqError("Groq chat completion failed.") from exc
        if response.status_code >= 400:
            raise GroqError(f"Groq chat completion failed with HTTP {response.status_code}.")
        try:
            content = response.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
        except (KeyError, IndexError, ValueError) as exc:
            raise GroqError("Groq returned something other than the expected JSON.") from exc
        return _parse_verdict(data, text, sources)


def _parse_verdict(data: dict, text: str, sources: list[TavilyResult]) -> AnalysisResult:
    stance_by_index = {
        int(s["index"]): _coerce(s.get("stance"), _STANCES, "context")
        for s in data.get("citationStances") or []
        if isinstance(s, dict) and isinstance(s.get("index"), int)
    }
    citation_id_by_index: dict[int, str] = {}
    citations: list[Citation] = []
    for index, source in enumerate(sources):
        if index not in stance_by_index:
            continue  # only cite sources the model actually used
        citation_id = f"s{len(citations) + 1}"
        citation_id_by_index[index] = citation_id
        citations.append(
            Citation(
                id=citation_id,
                source_name=source.title,
                title=source.title,
                url=source.url,
                published_at=source.published_at or "",
                stance=stance_by_index[index],
                trusted=False,
                excerpt=source.snippet[:280] or None,
            )
        )

    claims: list[Claim] = []
    for i, c in enumerate(data.get("claims") or []):
        if not isinstance(c, dict):
            continue
        start, end = _find_span(text, str(c.get("text") or ""))
        citation_ids = [
            citation_id_by_index[idx]
            for idx in c.get("sourceIndexes") or []
            if isinstance(idx, int) and idx in citation_id_by_index
        ]
        claims.append(
            Claim(
                id=f"c{i + 1}",
                start=start,
                end=end,
                assessment=_coerce(c.get("assessment"), _ASSESSMENTS, "unsupported"),
                reason=str(c.get("reason") or ""),
                citation_ids=citation_ids,
            )
        )

    confidence = data.get("confidence")
    confidence = max(0, min(100, int(confidence))) if isinstance(confidence, int | float) else 50

    return AnalysisResult(
        title=str(data.get("title") or "Untitled claim")[:200],
        verdict=_coerce(data.get("verdict"), _VERDICTS, "unverifiable"),
        confidence=confidence,
        summary=str(data.get("summary") or ""),
        category=str(data.get("category") or "General"),
        what_is_false=[str(v) for v in data.get("whatIsFalse") or [] if isinstance(v, str)],
        what_is_true=[str(v) for v in data.get("whatIsTrue") or [] if isinstance(v, str)],
        claims=claims,
        citations=citations,
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
        groq_api_key=settings.groq_api_key,
        groq_api_url=settings.groq_api_url,
        groq_model=settings.groq_model,
        tavily_api_key=settings.tavily_api_key,
        tavily_api_url=settings.tavily_api_url,
        embedder=get_embedding_provider(),
        ai_text_detector=get_ai_text_detector(),
        dedupe_max_cosine_distance=settings.dedupe_max_cosine_distance,
    )
