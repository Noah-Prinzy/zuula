"""Milestone E: turns a database seeded with the sample data (`python -m app.db.seed`, as
production was) into one holding real content only, without touching what real use added.

Removed: the nine named sample accounts and the `seed-*` rater pool, with everything they
own or wrote (ratings, comments, flags, sessions, API keys, notifications, broadcasts, audit
entries — the append-only trigger is lifted for that one delete — the accreditation
application); the fictional SAMPLE_REPORTS with their
submissions, annotations, moderation items, review cases and manipulation signals; the
seeded `model_evaluations` rows; the sample sources' invented crawl history.

Kept: every other account (real sign-ups), reports the live pipeline wrote, audit entries
with no sample actor, platform settings, the trusted-source registry itself.

Added: the real fact-checks (app/db/real_data.py) that aren't there yet, with no votes and
no embedding (run app/db/backfill_embeddings.py afterwards).

    python -m app.db.reset_real            # dry run: prints what would change, rolls back
    python -m app.db.reset_real --apply    # commits
    ... --drop-report fc-2026-0163 ...     # also remove these (e.g. test checks), repeatable

Take a `pg_dump` first: nothing here can be undone.
"""

import asyncio
import sys

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models as m
from app.db.real_data import load_real_reports
from app.db.sample_data import admin as stub_admin
from app.db.sample_data.fact_checks import SAMPLE_REPORTS
from app.db.seed import _dedupe_tracking_ids, insert_reports
from app.services.community import recompute_report_community

SAMPLE_EVALUATION_IDS = ("eval-f1", "eval-deepfake")


def _is_sample_user(column):
    return or_(column.in_([u.id for u in stub_admin.SAMPLE_USERS]), column.like("seed-%"))


async def reset_to_real(
    session: AsyncSession, *, drop_reports: tuple[str, ...] = ()
) -> dict[str, int]:
    """Returns rows changed per table ("+name" for inserts). Flushes, never commits."""
    changed: dict[str, int] = {}

    async def run(label: str, stmt) -> None:
        n = (await session.execute(stmt)).rowcount
        if n:
            changed[label] = changed.get(label, 0) + n

    report_ids = [r.id for r in SAMPLE_REPORTS] + list(drop_reports)
    gone_report = m.FactCheckReport.id.in_(report_ids)
    gone_reports = select(m.FactCheckReport.id).where(gone_report)
    gone_tracking = select(m.FactCheckReport.tracking_id).where(gone_report)
    gone_content_reports = select(m.ContentReport.id).where(
        m.ContentReport.report_id.in_(gone_reports)
    )
    gone_comments = select(m.RatingComment.id).where(
        or_(
            m.RatingComment.report_id.in_(gone_reports),
            _is_sample_user(m.RatingComment.user_id),
        )
    )
    gone_cases = select(m.ReviewCase.id).where(
        or_(
            m.ReviewCase.report_id.in_(gone_reports),
            m.ReviewCase.content_report_id.in_(gone_content_reports),
        )
    )
    sample_keys = select(m.ApiKey.id).where(_is_sample_user(m.ApiKey.user_id))
    sample_broadcasts = select(m.Broadcast.id).where(_is_sample_user(m.Broadcast.sent_by))

    # Leaves first, so no foreign key is ever left dangling.
    await run(
        "content_flags",
        delete(m.ContentFlag).where(
            or_(
                _is_sample_user(m.ContentFlag.user_id),
                m.ContentFlag.content_report_id.in_(gone_content_reports),
                m.ContentFlag.comment_id.in_(gone_comments),
            )
        ),
    )
    await run(
        "review_decisions",
        delete(m.ReviewDecision).where(
            or_(
                m.ReviewDecision.case_id.in_(gone_cases),
                m.ReviewDecision.report_id.in_(gone_reports),
                _is_sample_user(m.ReviewDecision.reviewer_id),
            )
        ),
    )
    await run("review_cases", delete(m.ReviewCase).where(m.ReviewCase.id.in_(gone_cases)))
    await run(
        "review_cases (unassigned)",
        update(m.ReviewCase)
        .where(_is_sample_user(m.ReviewCase.assignee_id))
        .values(assignee_id=None),
    )
    await run(
        "content_reports",
        delete(m.ContentReport).where(m.ContentReport.id.in_(gone_content_reports)),
    )
    await run(
        "content_reports (resolver cleared)",
        update(m.ContentReport)
        .where(_is_sample_user(m.ContentReport.resolved_by))
        .values(resolved_by=None),
    )
    await run(
        "rating_comments", delete(m.RatingComment).where(m.RatingComment.id.in_(gone_comments))
    )
    await run(
        "rating_comments (remover cleared)",
        update(m.RatingComment)
        .where(_is_sample_user(m.RatingComment.removed_by))
        .values(removed_by=None),
    )
    touched_reports = set(
        await session.scalars(
            select(m.Rating.report_id)
            .where(_is_sample_user(m.Rating.user_id), m.Rating.report_id.not_in(report_ids))
            .distinct()
        )
    )
    await run(
        "ratings",
        delete(m.Rating).where(
            or_(m.Rating.report_id.in_(gone_reports), _is_sample_user(m.Rating.user_id))
        ),
    )
    await run(
        "expert_annotations",
        delete(m.ExpertAnnotation).where(
            or_(
                m.ExpertAnnotation.report_id.in_(gone_reports),
                _is_sample_user(m.ExpertAnnotation.author_id),
            )
        ),
    )
    await run(
        "manipulation_signals",
        delete(m.ManipulationSignal).where(m.ManipulationSignal.report_id.in_(gone_reports)),
    )
    tracking = list(await session.scalars(gone_tracking))
    await run("fact_check_reports", delete(m.FactCheckReport).where(gone_report))
    await run(
        "submissions",
        delete(m.Submission).where(
            or_(m.Submission.tracking_id.in_(tracking), _is_sample_user(m.Submission.user_id))
        ),
    )
    await run(
        "submissions (sample key cleared)",
        update(m.Submission)
        .where(m.Submission.api_key_id.in_(sample_keys))
        .values(api_key_id=None),
    )
    await run(
        "api_usage_hourly",
        delete(m.ApiUsageHourly).where(m.ApiUsageHourly.api_key_id.in_(sample_keys)),
    )
    await run("api_keys", delete(m.ApiKey).where(m.ApiKey.id.in_(sample_keys)))
    await run(
        "notifications",
        delete(m.Notification).where(
            or_(
                _is_sample_user(m.Notification.user_id),
                m.Notification.broadcast_id.in_(sample_broadcasts),
            )
        ),
    )
    await run("broadcasts", delete(m.Broadcast).where(m.Broadcast.id.in_(sample_broadcasts)))
    for model in (m.Session, m.AlertSettings, m.AuthChallenge, m.OAuthIdentity):
        await run(model.__tablename__, delete(model).where(_is_sample_user(model.user_id)))
    await run(
        "accreditation_applications",
        delete(m.AccreditationApplication).where(
            _is_sample_user(m.AccreditationApplication.user_id)
        ),
    )
    await run(
        "accreditation_applications (reviewer cleared)",
        update(m.AccreditationApplication)
        .where(_is_sample_user(m.AccreditationApplication.reviewer_id))
        .values(reviewer_id=None),
    )
    # The audit log is append-only (a trigger, migration 0001). The sample entries record
    # actions no one took, and their actor keys block deleting the sample accounts, so the
    # trigger is lifted for this one delete only; ALTER TABLE is transactional, so a failure
    # anywhere in the reset leaves it enabled.
    await session.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_append_only"))
    await run("audit_log", delete(m.AuditLogEntry).where(_is_sample_user(m.AuditLogEntry.actor_id)))
    await session.execute(text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_append_only"))
    await run(
        "platform_settings (editor cleared)",
        update(m.PlatformSettings)
        .where(_is_sample_user(m.PlatformSettings.updated_by))
        .values(updated_by=None),
    )
    await run(
        "model_evaluations",
        delete(m.ModelEvaluation).where(m.ModelEvaluation.id.in_(SAMPLE_EVALUATION_IDS)),
    )
    await run("users", delete(m.User).where(_is_sample_user(m.User.id)))
    await run(
        "trusted_sources (crawl history cleared)",
        update(m.TrustedSource)
        .where(
            m.TrustedSource.id.in_([s.id for s in stub_admin.SAMPLE_SOURCES]),
            or_(m.TrustedSource.last_crawled.is_not(None), m.TrustedSource.crawl_ok.is_(False)),
        )
        .values(last_crawled=None, crawl_ok=True),
    )

    # Real reports whose votes came only from the rater pool now have none.
    for report in await session.scalars(
        select(m.FactCheckReport).where(m.FactCheckReport.id.in_(touched_reports))
    ):
        await recompute_report_community(session, report)

    present = set(await session.scalars(select(m.FactCheckReport.id)))
    real = [r for r in load_real_reports() if r.id not in present]
    if real:
        await insert_reports(session, {}, _dedupe_tracking_ids(real), real)
        for report in await session.scalars(
            select(m.FactCheckReport).where(m.FactCheckReport.id.in_([r.id for r in real]))
        ):
            await recompute_report_community(session, report)
            report.status_changed_at = None  # imported state, not a transition
        changed["+fact_check_reports"] = len(real)
        changed["+submissions"] = len(real)

    await session.flush()
    return changed


def _drop_reports(argv: list[str]) -> tuple[str, ...]:
    return tuple(argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "--drop-report")


async def _main() -> int:
    from app.db.session import get_engine, get_sessionmaker

    apply = "--apply" in sys.argv[1:]
    async with get_sessionmaker()() as session:
        changed = await reset_to_real(session, drop_reports=_drop_reports(sys.argv[1:]))
        users = (await session.execute(select(func.count()).select_from(m.User))).scalar_one()
        reports = (
            await session.execute(select(func.count()).select_from(m.FactCheckReport))
        ).scalar_one()
        for label, n in changed.items():
            print(f"{label}: {n}")
        print(f"Afterwards: {users} users, {reports} fact-check reports.")
        if apply:
            await session.commit()
            print("Committed.")
        else:
            await session.rollback()
            print("Dry run: rolled back. Pass --apply to commit.")
    await get_engine().dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
