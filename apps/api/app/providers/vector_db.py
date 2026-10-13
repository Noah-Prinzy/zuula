"""VectorDbProvider: where app/providers/analysis.py's GroqAnalysisProvider looks up a
near-duplicate claim's embedding, and where a newly written report's embedding gets indexed.

§4.2/§4.1 Layer 4 of the spec names Pinecone or Weaviate for vector search. The live demo
path keeps pgvector (`PgVectorProvider`) as the default: `fact_check_reports.embedding` is
already the system of record (HNSW index, migrations/versions/0004_embedding_dimensions.py),
so there's no second store to keep in sync, no extra monthly cost and no extra network hop —
free beats "spec-named" when the free option already does the job. `PineconeVectorProvider`
is the additive alternative that actually satisfies the spec's named technology choice,
selected with VECTOR_DB_PROVIDER=pinecone. Weaviate would serve the same role, but Pinecone's
free tier (Starter: one serverless index, no card required) is the lower-friction one to turn
on for this project's budget, so it's the one implemented; nothing here stops a
WeaviateVectorProvider being added behind the same switch later.

Both backends expose the same shape GroqAnalysisProvider needs: find the nearest existing
report's id and cosine distance, and index a newly written report's embedding so a later
claim can find it.
"""

import logging
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_analysis_settings
from app.db.models import FactCheckReport

logger = logging.getLogger("zuula.providers.vector_db")


@dataclass
class VectorMatch:
    report_id: str
    distance: float  # cosine distance: 0 = identical, 2 = opposite


class VectorDbProvider(Protocol):
    async def find_nearest(self, db: AsyncSession, embedding: list[float]) -> VectorMatch | None:
        """The closest existing report's id and cosine distance, or None if the index has
        nothing to offer. GroqAnalysisProvider compares `distance` against
        DEDUPE_MAX_COSINE_DISTANCE itself — this just finds the nearest neighbor."""
        ...

    async def find_similar(
        self, db: AsyncSession, embedding: list[float], *, limit: int
    ) -> list[VectorMatch]:
        """Up to `limit` existing reports, closest first — the same search as find_nearest,
        widened past one result. GroqAnalysisProvider uses this both for the dedupe check
        (closest result, same as find_nearest) and for local-evidence retrieval (the rest):
        reports similar enough to be useful grounding for the Explanation Generator without
        being a near-duplicate of the new claim. Empty list if the index has nothing to
        offer."""
        ...

    async def upsert(self, *, report_id: str, embedding: list[float]) -> None:
        """Index a newly written report's embedding so a later claim can find it."""
        ...


class PgVectorProvider:
    """The default: pgvector's cosine-distance operator against the existing
    `fact_check_reports.embedding` column (HNSW index) — no extra infrastructure, nothing to
    keep in sync."""

    async def find_nearest(self, db: AsyncSession, embedding: list[float]) -> VectorMatch | None:
        matches = await self.find_similar(db, embedding, limit=1)
        return matches[0] if matches else None

    async def find_similar(
        self, db: AsyncSession, embedding: list[float], *, limit: int
    ) -> list[VectorMatch]:
        distance = FactCheckReport.embedding.cosine_distance(embedding)
        rows = (
            await db.execute(
                select(FactCheckReport.id, distance.label("distance"))
                .where(FactCheckReport.embedding.is_not(None))
                .order_by(distance)
                .limit(limit)
            )
        ).all()
        return [
            VectorMatch(report_id=row.id, distance=row.distance)
            for row in rows
            if row.distance is not None
        ]

    async def upsert(self, *, report_id: str, embedding: list[float]) -> None:
        # Already persisted: the embedding is the `fact_check_reports.embedding` column,
        # written by the same INSERT that creates the row (app/worker/pipeline.py). There is
        # nothing else to index.
        pass


class PineconeVectorProvider:
    """§4.2/§4.1 Layer 4's named vector-DB choice, as an additive alternative: a Pinecone
    index holding only (report id -> embedding), queried over HTTPS with Pinecone's REST API
    directly (no vendor SDK — same house convention as app/providers/tavily.py's plain httpx
    calls to Tavily). `fact_check_reports` stays the source of truth for everything but the
    vector itself; a Pinecone match is resolved back to the real row by
    GroqAnalysisProvider._reuse_if_duplicate (app/providers/analysis.py)."""

    def __init__(self, *, api_key: str, host: str, timeout: float = 10.0):
        self._api_key = api_key
        self._host = host.rstrip("/")
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Api-Key": self._api_key, "Content-Type": "application/json"}

    async def find_nearest(self, db: AsyncSession, embedding: list[float]) -> VectorMatch | None:
        matches = await self.find_similar(db, embedding, limit=1)
        return matches[0] if matches else None

    async def find_similar(
        self, db: AsyncSession, embedding: list[float], *, limit: int
    ) -> list[VectorMatch]:
        import httpx

        payload = {"vector": embedding, "topK": limit, "includeValues": False}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._host}/query", json=payload, headers=self._headers()
                )
        except httpx.HTTPError:
            logger.warning("Pinecone query failed; treating as no matches", exc_info=True)
            return []
        if response.status_code >= 400:
            logger.warning("Pinecone query failed with HTTP %d", response.status_code)
            return []
        try:
            matches = response.json().get("matches") or []
        except ValueError:
            logger.warning("Pinecone returned something unexpected", exc_info=True)
            return []
        results = []
        for match in matches:
            score = match.get("score")
            if score is None or match.get("id") is None:
                continue
            # Pinecone's cosine metric returns similarity (1 = identical); GroqAnalysisProvider
            # compares distance (0 = identical) against DEDUPE_MAX_COSINE_DISTANCE /
            # LOCAL_EVIDENCE_MAX_COSINE_DISTANCE, same as PgVectorProvider's pgvector distance.
            results.append(VectorMatch(report_id=str(match["id"]), distance=1.0 - float(score)))
        return results

    async def upsert(self, *, report_id: str, embedding: list[float]) -> None:
        import httpx

        payload = {"vectors": [{"id": report_id, "values": embedding}]}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._host}/vectors/upsert", json=payload, headers=self._headers()
                )
            if response.status_code >= 400:
                logger.warning("Pinecone upsert failed with HTTP %d", response.status_code)
        except httpx.HTTPError:
            logger.warning("Pinecone upsert failed", exc_info=True)


def get_vector_db_provider() -> VectorDbProvider:
    """VECTOR_DB_PROVIDER: `pgvector` (the default — matches the live demo path exactly, no
    behaviour change when unset) or `pinecone`."""
    settings = get_analysis_settings()
    choice = settings.vector_db_provider.strip().lower()
    if choice not in ("pgvector", "pinecone"):
        raise NotImplementedError(
            f"Unknown VECTOR_DB_PROVIDER '{settings.vector_db_provider}': use 'pgvector' or "
            "'pinecone'."
        )
    if choice == "pgvector":
        return PgVectorProvider()
    if not settings.pinecone_api_key or not settings.pinecone_host:
        raise NotImplementedError(
            "VECTOR_DB_PROVIDER=pinecone needs PINECONE_API_KEY and PINECONE_HOST."
        )
    return PineconeVectorProvider(api_key=settings.pinecone_api_key, host=settings.pinecone_host)
