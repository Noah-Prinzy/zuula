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
"""

import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models as m
from app.providers.embedding import get_embedding_provider


def _claim_text(report: m.FactCheckReport) -> str:
    return report.submitted_text or report.title


async def backfill_embeddings(session: AsyncSession) -> int:
    """Embeds every FactCheckReport row with `embedding IS NULL`, using whichever
    EmbeddingProvider EMBEDDING_PROVIDER currently selects. Returns how many rows it filled
    in (rows whose claim text is empty are left as-is, same as the live pipeline)."""
    provider = get_embedding_provider()
    stmt = select(m.FactCheckReport).where(m.FactCheckReport.embedding.is_(None))
    reports = (await session.scalars(stmt)).all()
    filled = 0
    for report in reports:
        text = _claim_text(report)
        if not text.strip():
            continue
        report.embedding = provider.embed(text)
        filled += 1
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
            "traffic. Set EMBEDDING_PROVIDER=sentence-transformers and rerun to compute real "
            "embeddings."
        )
        return 1

    async with get_sessionmaker()() as session:
        filled = await backfill_embeddings(session)
        await session.commit()
    await get_engine().dispose()
    print(f"Backfilled embeddings for {filled} report(s).")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
