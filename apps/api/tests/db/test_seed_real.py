"""Real fact-check import (app/db/real_data.py), seeded via `seed(session, include_real=True)`
(`python -m app.db.seed --real` / `SEED_REAL_DATA=1`). Separate from test_seed.py: that suite's
`db` fixture is seeded without real data on purpose, so those assertions (exact match against
the fictional SAMPLE_REPORTS) stay unaffected — real data is additive, never a substitute."""

import asyncio
import json

import pytest
from alembic import command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.db import models as m
from app.db.real_data import SEED_DATA_DIR, load_real_reports
from app.db.sample_data.fact_checks import SAMPLE_REPORTS
from tests.dbutil import TEST_DATABASE_URL, alembic_config, recreate_database, seed_database

REAL_DB_URL = f"{TEST_DATABASE_URL}_real"
EVAL_DATA_DIR = SEED_DATA_DIR.parent / "eval"


def test_real_reports_load_from_the_seed_split_only():
    reports = load_real_reports()
    assert len(reports) > 0
    assert {r.id for r in reports} == {f"fc-real-{i:04d}" for i in range(1, len(reports) + 1)}
    assert len({r.tracking_id for r in reports}) == len(reports)  # tracking ids are unique

    # None of the held-out eval split's claims leak into what gets seeded.
    eval_urls = {
        rec["source_url"]
        for path in EVAL_DATA_DIR.glob("*.json")
        for rec in json.loads(path.read_text())
    }
    assert eval_urls, "eval split should be non-empty for this to be a meaningful check"
    assert eval_urls.isdisjoint({r.source_url for r in reports})


def test_real_reports_carry_no_fabricated_community_votes():
    for r in load_real_reports():
        assert r.community.accurate.public == r.community.accurate.journalist == 0
        assert r.community.accurate.expert == 0
        assert r.community.inaccurate.public == r.community.inaccurate.journalist == 0
        assert r.community.inaccurate.expert == 0
        assert r.community.score.ccs is None
        assert r.human_review is None


def test_real_reports_have_valid_verdicts_and_claim_spans():
    from app.schemas.common import Verdict

    valid_verdicts = set(Verdict.__args__)
    for r in load_real_reports():
        assert r.verdict in valid_verdicts
        assert len(r.claims) == 1
        assert r.claims[0].start == 0
        assert r.claims[0].end == len(r.submitted_text)
        assert r.submitted_text == r.title  # the claim itself, with no real submission to show


@pytest.fixture(scope="module")
def real_migrated_db_url() -> str:
    asyncio.run(recreate_database(REAL_DB_URL))
    command.upgrade(alembic_config(REAL_DB_URL), "head")
    asyncio.run(seed_database(REAL_DB_URL, include_real=True))
    return REAL_DB_URL


@pytest.fixture
async def real_db(real_migrated_db_url):
    engine = create_async_engine(real_migrated_db_url, poolclass=NullPool)
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


async def test_include_real_seeds_real_reports_alongside_the_fictional_ones(real_db):
    ids = set((await real_db.scalars(select(m.FactCheckReport.id))).all())
    real_ids = {r.id for r in load_real_reports()}
    assert real_ids <= ids
    assert {r.id for r in SAMPLE_REPORTS} <= ids  # additive, not a replacement


async def test_real_reports_are_seeded_with_zero_ratings(real_db):
    rows = (
        await real_db.scalars(
            select(m.FactCheckReport).where(m.FactCheckReport.id.like("fc-real-%"))
        )
    ).all()
    assert len(rows) == len(load_real_reports())
    for row in rows:
        assert row.accurate_public == row.inaccurate_public == 0
        assert row.ccs is None
    rating_count = (
        await real_db.scalars(select(m.Rating).where(m.Rating.report_id.like("fc-real-%")))
    ).all()
    assert rating_count == []
