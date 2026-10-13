"""SourceVerifier: the Source Verification Engine half of §4.1 Layer 3 — cross-referencing a
claim against credible web sources, kept as a distinct step from the Explanation Generator
(app/providers/explanation.py) that turns that evidence into the report's verdict and
wording. The two used to be fused into one function inside app/providers/analysis.py; this
split matches the spec's named architecture (an "LLM Verification Module" and separate
"Explanation Generator") while keeping the same one-Tavily-search-per-claim cost
(app/providers/tavily.py's free tier) — see app/providers/explanation.py's docstring for why
this stays two modules rather than two LLM calls.

app/providers/analysis.py's GroqAnalysisProvider composes this module's evidence with
explanation.py's wording into one claim-level AnalysisResult.
"""

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TrustedSource
from app.providers.tavily import TavilyResult, TavilySearchError, tavily_search

logger = logging.getLogger("zuula.providers.source_verification")

# Below this many results, a trusted-only search is too sparse to prefer over an open one —
# the registry only has 12 of its SOURCE_TARGET=50 sources seeded so far (app/db/sample_data/
# admin.py), so a hard restriction to it would tank evidence coverage for most claims.
_RESTRICTED_SEARCH_MIN_RESULTS = 2


@dataclass
class EvidenceBundle:
    """What the Source Verification Engine hands the Explanation Generator: the web evidence
    it found, and which domains were considered trusted (so citations can be marked).

    `sources` may carry local-evidence entries from app/providers/analysis.py's
    GroqAnalysisProvider._augment_with_local_evidence (prepended, per `local_evidence_count`)
    ahead of this module's own Tavily results — see docs/adr/0004-ai-engine-retrieval.md.
    This module only ever produces `local_evidence_count=0` bundles itself."""

    sources: list[TavilyResult]
    trusted_domains: list[str]
    # How many of the leading `sources` entries are local-evidence matches (already-verified
    # Zuula reports) rather than this module's own live Tavily results — see
    # app/providers/explanation.py's _sources_block and _parse_explanation, which treat them
    # as always trusted and label them distinctly for the model.
    local_evidence_count: int = 0


async def _trusted_domains(db: AsyncSession) -> list[str]:
    rows = await db.execute(select(TrustedSource.domain).where(TrustedSource.active.is_(True)))
    return [domain for (domain,) in rows.all()]


def domain_of(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def is_trusted(url: str, trusted_domains: frozenset[str]) -> bool:
    domain = domain_of(url)
    return any(domain == d or domain.endswith(f".{d}") for d in trusted_domains)


class SourceVerifier:
    """Interface the Explanation Generator (and tests) depend on, kept narrow on purpose:
    gather the evidence for a claim, nothing about wording a verdict."""

    async def gather_evidence(self, db: AsyncSession, text: str) -> EvidenceBundle:
        raise NotImplementedError


class TavilySourceVerifier(SourceVerifier):
    """Cross-references a claim against web evidence via Tavily, restricted to the
    admin-managed trusted-source registry (`TrustedSource`, FR-DETECT-06) when it has enough
    to offer."""

    def __init__(self, *, tavily_api_key: str, tavily_api_url: str, timeout: float = 30.0):
        self._tavily_api_key = tavily_api_key
        self._tavily_api_url = tavily_api_url
        self._timeout = timeout

    async def gather_evidence(self, db: AsyncSession, text: str) -> EvidenceBundle:
        trusted_domains = await _trusted_domains(db)
        try:
            sources = await self._search(text=text, trusted_domains=trusted_domains)
        except TavilySearchError:
            logger.warning("Tavily search failed; verifying without web evidence", exc_info=True)
            sources = []
        return EvidenceBundle(sources=sources, trusted_domains=trusted_domains)

    async def _search(self, *, text: str, trusted_domains: list[str]) -> list[TavilyResult]:
        """One search per claim (the module's cost constraint), restricted to the trusted
        registry when it has enough to offer. Only 12 of SOURCE_TARGET=50 sources are seeded
        today, so a hard restriction would starve most claims of evidence — fall back to an
        unrestricted search instead of returning sparse or empty results."""
        query = text[:400]
        if trusted_domains:
            restricted = await tavily_search(
                api_key=self._tavily_api_key,
                api_url=self._tavily_api_url,
                query=query,
                include_domains=trusted_domains,
                timeout=self._timeout,
            )
            if len(restricted) >= _RESTRICTED_SEARCH_MIN_RESULTS:
                return restricted
            logger.info(
                "Trusted-source search returned only %d result(s) (of %d trusted domains); "
                "falling back to an unrestricted search",
                len(restricted),
                len(trusted_domains),
            )
        return await tavily_search(
            api_key=self._tavily_api_key,
            api_url=self._tavily_api_url,
            query=query,
            timeout=self._timeout,
        )
