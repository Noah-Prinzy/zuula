"""app/db/reset_real.py (Milestone E): a sample-seeded database, plus what real use adds to it,
reset to real content only. Own database, like test_seed_real.py: the reset deletes most of
what the shared `db` fixture's assertions rely on."""

import asyncio
from datetime import UTC, datetime

import pytest
from alembic import command
from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.db import models as m
from app.db.real_data import _zero_community, load_real_reports
from app.db.reset_real import reset_to_real
from app.db.sample_data import admin as stub_admin
from app.db.sample_data.fact_checks import SAMPLE_REPORTS
from app.db.seed import insert_reports
from app.services.community import recompute_report_community
from tests.dbutil import TEST_DATABASE_URL, alembic_config, recreate_database, seed_database

RESET_DB_URL = f"{TEST_DATABASE_URL}_reset"
NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
REAL_USER = "usr_real0000000001"
LIVE_REPORT = "fc-2026-0200"  # written by the live pipeline: kept
TEST_REPORT = "fc-2026-0201"  # a test check: dropped on request


async def _add_real_use(session: AsyncSession) -> None:
    session.add(
        m.User(
            id=REAL_USER,
            name="Real person",
            email="real@example.org",
            role="public",
            status="active",
            created_at=NOW,
        )
    )
    await session.flush()
    template = SAMPLE_REPORTS[0]
    reports = [
        template.model_copy(
            update={
                "id": rid,
                "tracking_id": tid,
                "annotations": [],
                "community": _zero_community(),
            }
        )
        for rid, tid in ((LIVE_REPORT, "ZL-REAL-QK"), (TEST_REPORT, "ZL-TEST-QK"))
    ]
    await insert_reports(session, {}, {r.id: r.tracking_id for r in reports}, reports)
    await session.execute(
        insert(m.Rating),
        [
            {
                "report_id": LIVE_REPORT,
                "user_id": uid,
                "vote": "accurate",
                "rater_role": "public",
                "created_at": NOW,
                "updated_at": NOW,
            }
            for uid in (REAL_USER, "seed-p001")
        ],
    )
    session.add(
        m.AuditLogEntry(
            at=NOW,
            actor_id=None,
            actor_name="Maintenance",
            actor_role="admin",
            action="user.suspend",
            target="u1",
            detail="",
            ip="",
        )
    )
    await session.flush()
    report = await session.get(m.FactCheckReport, LIVE_REPORT)
    await recompute_report_community(session, report)
    await session.flush()


@pytest.fixture(scope="module")
def reset_db_url() -> str:
    asyncio.run(recreate_database(RESET_DB_URL))
    command.upgrade(alembic_config(RESET_DB_URL), "head")
    asyncio.run(seed_database(RESET_DB_URL))
    return RESET_DB_URL


@pytest.fixture
async def db(reset_db_url):
    engine = create_async_engine(reset_db_url, poolclass=NullPool)
    async with engine.connect() as conn:
        outer = await conn.begin()
        session = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            await _add_real_use(session)
            yield session
        finally:
            await session.close()
            await outer.rollback()
    await engine.dispose()


async def _count(db: AsyncSession, model, *where) -> int:
    return (await db.execute(select(func.count()).select_from(model).where(*where))).scalar_one()


async def test_sample_data_goes_and_real_use_stays(db):
    await reset_to_real(db, drop_reports=(TEST_REPORT,))

    users = set(await db.scalars(select(m.User.id)))
    assert users == {REAL_USER}

    report_ids = set(await db.scalars(select(m.FactCheckReport.id)))
    assert not report_ids & {r.id for r in SAMPLE_REPORTS}
    assert TEST_REPORT not in report_ids
    assert report_ids == {LIVE_REPORT} | {r.id for r in load_real_reports()}
    assert await _count(db, m.Submission, m.Submission.tracking_id == "ZL-TEST-QK") == 0
    assert await _count(db, m.Submission) == len(report_ids)

    # The live report keeps the real vote only, and its counts follow.
    live = await db.get(m.FactCheckReport, LIVE_REPORT)
    assert set(await db.scalars(select(m.Rating.user_id))) == {REAL_USER}
    assert live.accurate_public == 1

    for model in (
        m.Broadcast,
        m.ApiKey,
        m.Session,
        m.Notification,
        m.ContentReport,
        m.ContentFlag,
        m.ReviewCase,
        m.ReviewDecision,
        m.ManipulationSignal,
        m.ExpertAnnotation,
        m.RatingComment,
        m.AccreditationApplication,
        m.ModelEvaluation,
    ):
        assert await _count(db, model) == 0, model.__tablename__

    actors = list(await db.scalars(select(m.AuditLogEntry.actor_name)))
    assert actors == ["Maintenance"]

    sources = (await db.scalars(select(m.TrustedSource))).all()
    assert len(sources) == 50  # the registry itself stays
    assert all(s.last_crawled is None and s.crawl_ok for s in sources)
    assert await _count(db, m.PlatformSettings) == 1


async def test_real_reports_arrive_with_no_votes(db):
    await reset_to_real(db)
    real = (
        await db.scalars(select(m.FactCheckReport).where(m.FactCheckReport.id.like("fc-real-%")))
    ).all()
    assert len(real) == len(load_real_reports())
    assert all(r.accurate_public == r.inaccurate_public == 0 and r.ccs is None for r in real)


async def test_running_it_twice_changes_nothing_more(db):
    first = await reset_to_real(db, drop_reports=(TEST_REPORT,))
    assert first["users"] > len(stub_admin.SAMPLE_USERS)  # the named accounts and the raters
    assert await reset_to_real(db, drop_reports=(TEST_REPORT,)) == {}


async def test_the_audit_log_is_append_only_again_afterwards(db):
    await reset_to_real(db)
    with pytest.raises(DBAPIError, match="append-only"):
        async with db.begin_nested():
            await db.execute(delete(m.AuditLogEntry))
