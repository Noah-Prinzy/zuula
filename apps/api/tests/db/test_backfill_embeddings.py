"""app/db/backfill_embeddings.py: fills in `embedding` for reports seeded without one (both
the fictional SAMPLE_REPORTS and, with --real, the real AFP-verified reports from
app/db/real_data.py). Separate database from test_seed.py/test_seed_real.py so backfilling
here never affects their NULL-embedding assertions."""

import asyncio

import pytest
from alembic import command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.db import models as m
from app.db.backfill_embeddings import backfill_embeddings
from app.db.real_data import load_real_reports
from app.providers.embedding import EMBEDDING_DIMENSIONS, stub_embedding
from tests.dbutil import TEST_DATABASE_URL, alembic_config, recreate_database, seed_database

BACKFILL_DB_URL = f"{TEST_DATABASE_URL}_backfill"


@pytest.fixture(scope="module")
def backfill_migrated_db_url() -> str:
    asyncio.run(recreate_database(BACKFILL_DB_URL))
    command.upgrade(alembic_config(BACKFILL_DB_URL), "head")
    asyncio.run(seed_database(BACKFILL_DB_URL, include_real=True))
    return BACKFILL_DB_URL


@pytest.fixture
async def backfill_db(backfill_migrated_db_url):
    """A fresh transaction per test, rolled back afterwards — every test starts from the same
    freshly-seeded, embedding=NULL state, same as test_seed_real.py's `real_db`."""
    engine = create_async_engine(backfill_migrated_db_url, poolclass=NullPool)
    async with engine.connect() as conn:
        outer = await conn.begin()
        session = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            await session.close()
            await outer.rollback()
    await engine.dispose()


async def test_seeded_reports_start_with_no_embedding(backfill_db):
    rows = (await backfill_db.scalars(select(m.FactCheckReport.embedding))).all()
    assert rows  # sanity: there are seeded reports to backfill
    assert all(e is None for e in rows)


async def test_backfill_fills_every_seeded_row(backfill_db):
    filled = await backfill_embeddings(backfill_db)
    reports = (await backfill_db.scalars(select(m.FactCheckReport))).all()
    assert filled == len(reports)  # every seeded report has non-empty submitted_text
    for report in reports:
        assert report.embedding is not None
        assert len(report.embedding) == EMBEDDING_DIMENSIONS


async def test_backfill_only_touches_rows_still_missing_an_embedding(backfill_db):
    first_pass = await backfill_embeddings(backfill_db)
    assert first_pass > 0
    reports = (await backfill_db.scalars(select(m.FactCheckReport))).all()
    before = {r.id: list(r.embedding) for r in reports}

    second_pass = await backfill_embeddings(backfill_db)

    reports = (await backfill_db.scalars(select(m.FactCheckReport))).all()
    after = {r.id: list(r.embedding) for r in reports}
    assert second_pass == 0
    assert before == after


async def test_backfill_embeds_the_real_reports_own_claim_text(backfill_db, monkeypatch):
    """Stands in for the real `sentence-transformers` path (EMBEDDING_PROVIDER=
    sentence-transformers) with a provider that just records what text it was asked to embed
    — downloading the real model is exactly what the suite must never trigger. The point of
    the test is that backfill feeds the provider each real report's actual claim text
    (`submitted_text`, set by app/db/real_data.py to the AFP claim itself), not something
    invented for this script, and that every one of the 363 real reports ends up with a
    populated embedding."""

    class RecordingProvider:
        def __init__(self):
            self.seen: list[str] = []

        async def embed(self, text):
            self.seen.append(text)
            return stub_embedding(text)

    provider = RecordingProvider()
    monkeypatch.setattr("app.db.backfill_embeddings.get_embedding_provider", lambda: provider)

    await backfill_embeddings(backfill_db)

    real_reports = load_real_reports()
    rows = (
        await backfill_db.scalars(
            select(m.FactCheckReport).where(m.FactCheckReport.id.like("fc-real-%"))
        )
    ).all()
    assert len(rows) == len(real_reports)
    for row in rows:
        assert row.embedding is not None
        assert len(row.embedding) == EMBEDDING_DIMENSIONS
    assert {r.submitted_text for r in real_reports} <= set(provider.seen)


async def test_all_replaces_vectors_from_another_model(backfill_db):
    # Milestone D7: production's reports carry placeholder (stub) vectors; switching to a
    # real model means every row is re-embedded, not just the empty ones.
    first = await backfill_embeddings(backfill_db)
    assert first > 0
    assert await backfill_embeddings(backfill_db) == 0
    assert await backfill_embeddings(backfill_db, replace_all=True) == first
