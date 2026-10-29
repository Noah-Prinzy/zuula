"""app/db/trusted_sources.py (Milestone D8): the approved sources that take the registry to
FR-DETECT-06's 50, and the add-only-what's-missing step production runs."""

from sqlalchemy import func, select

from app.db import models as m
from app.db.models.platform import SOURCE_TYPES
from app.db.sample_data.admin import SAMPLE_SOURCES, SOURCE_TARGET
from app.db.trusted_sources import APPROVED_SOURCES, add_missing_sources


def test_the_approved_list_reaches_the_target_without_repeats():
    domains = [s.domain for s in APPROVED_SOURCES] + [s.domain for s in SAMPLE_SOURCES]
    assert len(domains) == len(set(domains)) == SOURCE_TARGET
    for s in APPROVED_SOURCES:
        assert s.type in SOURCE_TYPES and s.tier in (1, 2, 3) and s.languages
        assert s.domain == s.domain.lower() and "/" not in s.domain and "www." not in s.domain


async def test_the_seeded_registry_holds_all_fifty(db):
    count = await db.scalar(select(func.count()).select_from(m.TrustedSource))
    assert count >= SOURCE_TARGET
    assert await add_missing_sources(db) == 0  # already there: nothing to add


async def test_an_admins_edit_survives_and_a_removed_source_comes_back(db):
    who = await db.scalar(select(m.TrustedSource).where(m.TrustedSource.domain == "who.int"))
    who.active, who.tier = False, 3
    await db.delete(
        await db.scalar(select(m.TrustedSource).where(m.TrustedSource.domain == "ubos.org"))
    )
    await db.flush()

    assert await add_missing_sources(db) == 1
    who = await db.scalar(select(m.TrustedSource).where(m.TrustedSource.domain == "who.int"))
    assert (who.active, who.tier) == (False, 3)
    ubos = await db.scalar(select(m.TrustedSource).where(m.TrustedSource.domain == "ubos.org"))
    assert ubos.active and ubos.last_crawled is None
