"""Fills in `fact_check_reports.embedding` for rows that were seeded without one.

GroqAnalysisProvider's dedupe check (app/providers/analysis.py) only ever reads an embedding
the live pipeline wrote (app/worker/pipeline.py: `embedding=analysis.embedding`). app/db/seed.py
never computes one for the rows it inserts, so every seeded report — the fictional
SAMPLE_REPORTS and, with --real/SEED_REAL_DATA=1, the 363 real AFP-verified reports
(app/db/real_data.py) — is seeded with `embedding IS NULL` and can never be found by that
nearest-neighbor search. This fills those rows in after the fact, using the same
EmbeddingProvider interface the live pipeline uses (app/providers/embedding.py), so it's a
seeded report's own `submitted_text` (the claim text itself for real reports, same as what the
live pipeline would have embedded) that ends up in the vector, not something invented for this
script.

Like SEED_REAL_DATA/`--real` opting into real fact-checks, `get_embedding_provider()` only
returns the real `sentence-transformers` model when EMBEDDING_PROVIDER is set to it —
it defaults to `stub` so routine dev/CI never downloads it. Run this after seeding (fresh or
already-seeded — it only ever touches rows with no embedding yet):

    EMBEDDING_PROVIDER=sentence-transformers python -m app.db.backfill_embeddings

`--all` re-embeds every report, not only empty ones: needed after switching models
(vectors from different models can't be compared), e.g. production's placeholder
vectors from before Milestone D7 (`EMBEDDING_PROVIDER=gemini ... --all`).
"""

import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models as m
from app.providers.embedding import (
    EmbeddingError,
    StubEmbeddingProvider,
    get_embedding_provider,
)


def _claim_text(report: m.FactCheckReport) -> str:
    return report.submitted_text or report.title


# A hosted model can refuse a burst (429) or blip; one row's failure shouldn't lose the rest.
_RETRY_DELAYS = (2, 5, 15, 30)


async def _embed_with_retries(provider, text: str) -> list[float]:
    for delay in (*_RETRY_DELAYS, None):
        try:
            return await provider.embed(text)
        except EmbeddingError:
            if delay is None:
                raise
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")


async def backfill_embeddings(
    session: AsyncSession, *, replace_all: bool = False, commit_every: int = 0
) -> int:
    """Embeds every FactCheckReport row with `embedding IS NULL` (every row, with
    `replace_all`), using whichever EmbeddingProvider EMBEDDING_PROVIDER currently selects.
    Returns how many rows it filled in (rows whose claim text is empty are left as-is, same
    as the live pipeline). With `commit_every`, commits after that many rows, so a run
    stopped part way keeps what it did (rerunning without --all finishes the rest only if
    the old vectors were empty)."""
    provider = get_embedding_provider()
    stmt = select(m.FactCheckReport).order_by(m.FactCheckReport.id)
    if not replace_all:
        stmt = stmt.where(m.FactCheckReport.embedding.is_(None))
    reports = (await session.scalars(stmt)).all()
    filled = 0
    for report in reports:
        text = _claim_text(report)
        if not text.strip():
            continue
        report.embedding = await _embed_with_retries(provider, text)
        filled += 1
        if commit_every and filled % commit_every == 0:
            await session.commit()
            print(f"  {filled} of {len(reports)} done", flush=True)
    await session.flush()
    return filled


async def _main() -> int:
    from app.core.config import get_analysis_settings
    from app.db.session import get_engine, get_sessionmaker

    settings = get_analysis_settings()
    if settings.embedding_provider.strip().lower() == "stub":
        print(
            "EMBEDDING_PROVIDER is 'stub' (the default), so this would only backfill "
            "placeholder vectors the dedupe check can't meaningfully match against real "
            "traffic. Set EMBEDDING_PROVIDER=gemini (with GEMINI_API_KEY) or "
            "sentence-transformers (local) and rerun to compute real embeddings."
        )
        return 1
    if isinstance(get_embedding_provider(), StubEmbeddingProvider):
        # e.g. EMBEDDING_PROVIDER=gemini without GEMINI_API_KEY: never write placeholders.
        print(f"EMBEDDING_PROVIDER={settings.embedding_provider} is missing its key.")
        return 1

    async with get_sessionmaker()() as session:
        filled = await backfill_embeddings(
            session, replace_all="--all" in sys.argv, commit_every=25
        )
        await session.commit()
    await get_engine().dispose()
    print(f"Backfilled embeddings for {filled} report(s).")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
