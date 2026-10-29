"""The seeded database reproduces the sample data: same ids, and community scores identical
to the sample data's own, even though they're now derived from individual votes."""

from sqlalchemy import func, select

from app.db import models as m
from app.db.sample_data.admin import SAMPLE_AUDIT, SAMPLE_SOURCES, SAMPLE_USERS
from app.db.sample_data.fact_checks import SAMPLE_REPORTS
from app.db.sample_data.review import SAMPLE_CASES
from app.services.community import community_score, report_counts


async def test_every_sample_report_is_seeded_with_its_stub_score(db):
    reports = {r.id: r for r in (await db.scalars(select(m.FactCheckReport))).all()}
    assert set(reports) == {r.id for r in SAMPLE_REPORTS}

    for stub in SAMPLE_REPORTS:
        row = reports[stub.id]
        accurate, inaccurate = report_counts(row)
        assert accurate == stub.community.accurate, stub.id
        assert inaccurate == stub.community.inaccurate, stub.id
        assert row.ccs == stub.community.score.ccs, stub.id
        assert row.community_status == stub.community.score.status, stub.id
        assert community_score(accurate, inaccurate) == stub.community.score


async def test_rating_rows_add_up_to_the_counts(db):
    total_votes = (await db.execute(select(func.count()).select_from(m.Rating))).scalar_one()
    assert total_votes == sum(r.community.score.total for r in SAMPLE_REPORTS)


async def test_named_votes_keep_the_role_they_were_cast_with(db):
    # Esther Atim (u3) commented as a public user before her promotion to expert on 20 Sep
    # (audit entry a10): her vote stays weighted as public (ADR 0002 §4, decision 6a).
    rating = (await db.scalars(select(m.Rating).where(m.Rating.user_id == "u3"))).first()
    assert rating is not None
    assert rating.rater_role == "public"
    user = await db.get(m.User, "u3")
    assert user.role == "expert"


async def test_sample_ids_are_preserved(db):
    assert {u.id for u in SAMPLE_USERS} <= set((await db.scalars(select(m.User.id))).all())
    assert {c.id for c in SAMPLE_CASES} <= set((await db.scalars(select(m.ReviewCase.id))).all())
    source_ids = set((await db.scalars(select(m.TrustedSource.id))).all())
    # The 12 sample sources keep their ids; app/db/trusted_sources.py adds 38 real ones.
    assert {s.id for s in SAMPLE_SOURCES} <= source_ids and len(source_ids) == 50
    audit_ids = set((await db.scalars(select(m.AuditLogEntry.id))).all())
    assert audit_ids == {int(e.id.removeprefix("a")) for e in SAMPLE_AUDIT}


async def test_tracking_id_collision_in_sample_data_is_resolved(db):
    tids = (await db.scalars(select(m.FactCheckReport.tracking_id))).all()
    assert len(tids) == len(set(tids))
    r160 = await db.get(m.FactCheckReport, "fc-2026-0160")
    r161 = await db.get(m.FactCheckReport, "fc-2026-0161")
    assert r160.tracking_id == "ZL-7767-QK"
    assert r161.tracking_id == "ZL-7868-QK"


async def test_platform_settings_default_to_the_rules(db):
    from app.core import rules

    row = await db.get(m.PlatformSettings, 1)
    assert row.settings["weights"] == rules.CCS_WEIGHTS
    assert row.settings["slaHours"] == rules.REVIEW_SLA_HOURS
    assert (
        row.settings["thresholds"]["suspendedRatings"]
        == (rules.CCS_STATUS_THRESHOLDS["suspended"]["min_ratings"])
    )
