"""Loads the sample data (app/db/sample_data/*, transliterated from apps/web/lib/mock/*) into a
freshly migrated database: for local dev (`python -m app.db.seed`) and for the test suite
(tests/db/conftest.py). Never run against production.

The sample reports only carry aggregate rating counts ("402 public users said accurate"), but
the schema stores individual votes and derives counts from them (ADR 0002 §4). So the seed
creates a pool of clearly-labelled sample raters (`seed-p001`, `…@seed.zuula.invalid`) and
casts exactly as many votes as each sample report's counts, after the named votes the sample
data does carry (rating comments, Amina's rating history). The seeded scores therefore come
out identical to the sample data's own scores — tests/db/test_seed.py checks that.

`python -m app.db.seed --real` (or `SEED_REAL_DATA=1`) additionally loads real, human-verified
fact-checks from `data/fact-checks/seed/*.json` (app/db/real_data.py) alongside the fictional
sample reports, rather than instead of them.
"""

import asyncio
import hashlib
import os
import secrets
import sys
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rules
from app.db import models as m
from app.db.real_data import load_real_reports
from app.db.sample_data import account as stub_account
from app.db.sample_data import admin as stub_admin
from app.db.sample_data import notifications as stub_notifications
from app.db.sample_data import review as stub_review
from app.db.sample_data.fact_checks import SAMPLE_REPORTS
from app.schemas.fact_check import FactCheckReport as FactCheckReportSchema
from app.services.auth import hash_password
from app.services.community import recompute_report_community
from app.worker.pipeline import PIPELINES, STEP_SECONDS

# The sample data is pinned to 21 Sep 2026 (apps/web/lib/mock/*); relative seed timestamps
# (session activity, pool accounts) hang off the same instant.
SEED_NOW = datetime(2026, 9, 21, 9, 0, tzinfo=UTC)
POOL_CREATED = datetime(2026, 1, 1, tzinfo=UTC)
RATER_ROLES = ("public", "journalist", "expert")

# Whose account the "my …" sample data belongs to: Amina, the public sample user
# (P2's stub "public" session user), and Sarah, the sample journalist, for API keys.
SAMPLE_OWNER = "u6"
SAMPLE_KEYS_OWNER = "u4"

# Sign-in password for the nine named sample accounts (mary@example.com, …), so local dev and
# the contract tests can sign in for real. Sample data only — it never exists in production.
# The sample raters have no password: they can't sign in.
SAMPLE_PASSWORD = "zuula-sample-password"

_SUBMISSION_TYPE = {
    "text": "text",
    "url": "url",
    "image": "media",
    "audio": "media",
    "video": "media",
}


def _dump(model) -> dict:
    return model.model_dump(by_alias=True, mode="json", exclude_none=True)


def _unusable_hash() -> str:
    """A SHA-256 of random bytes: fills a token/secret column for sample rows no one can use."""
    return hashlib.sha256(secrets.token_bytes(32)).hexdigest()


def _dedupe_tracking_ids(reports: list[FactCheckReportSchema]) -> dict[str, str]:
    """report id -> tracking id. The P2/frontend sample generator maps both fc-2026-0160 and
    fc-2026-0161 to ZL-7767-QK (`n.replace(/[01]/g, "7")`); tracking ids are unique in the
    database, so the later report of any collision gets 1 -> 8 instead (8 is in the
    TrackingId alphabet). Lowest report id keeps the original."""
    taken: set[str] = set()
    result: dict[str, str] = {}
    for r in sorted(reports, key=lambda r: r.id):
        tid = r.tracking_id
        if tid in taken:
            n = r.id[-4:]
            tid = f"ZL-{n.replace('0', '7').replace('1', '8')}-QK"
        if tid in taken:
            raise ValueError(f"Can't derive a unique tracking id for {r.id}")
        taken.add(tid)
        result[r.id] = tid
    return result


def _include_real_data() -> bool:
    return "--real" in sys.argv[1:] or os.environ.get("SEED_REAL_DATA") == "1"


async def seed(session: AsyncSession, *, include_real: bool | None = None) -> None:
    """`include_real` loads `data/fact-checks/seed/*.json` (real, human-verified fact-checks)
    alongside the fictional SAMPLE_REPORTS, instead of replacing them: local dev and the test
    suite still get the rich fictional examples (ratings, annotations, a human review case)
    that exercise every feature, plus real content for a fuller library. Defaults to the
    `--real` CLI flag / `SEED_REAL_DATA=1` env var so callers that don't ask for it (the test
    suite's `seed(session)`) keep today's fictional-only behaviour."""
    reports = (
        [*SAMPLE_REPORTS, *load_real_reports()]
        if (include_real if include_real is not None else _include_real_data())
        else SAMPLE_REPORTS
    )
    users_by_name = await _seed_users(session, reports)
    tracking_ids = _dedupe_tracking_ids(reports)
    await _seed_submissions_and_reports(session, users_by_name, tracking_ids, reports)
    await _seed_ratings(session, users_by_name, reports)
    await _seed_review(session, users_by_name)
    await _seed_admin(session, users_by_name)
    await _seed_account(session)
    await session.flush()


async def _seed_users(
    session: AsyncSession, reports: list[FactCheckReportSchema]
) -> dict[str, str]:
    rows = []
    password_hash = hash_password(SAMPLE_PASSWORD)  # one bcrypt run, shared: sample data only
    for u in stub_admin.SAMPLE_USERS:
        joined = datetime.combine(u.joined, datetime.min.time(), UTC)
        rows.append(
            {
                "id": u.id,
                "name": u.name,
                "email": u.email,
                "password_hash": password_hash,
                "role": u.role,
                "status": u.status,
                "two_factor_enabled": u.role in rules.TWO_FACTOR_ROLES,
                "email_verified_at": joined,
                "created_at": joined,
                "last_active_at": datetime.combine(u.last_active, datetime.min.time(), UTC),
            }
        )

    # Enough sample raters of each role to cast every report's votes (real reports seed with
    # none, so they never raise these maximums).
    needed = {
        role: max(
            getattr(r.community.accurate, role) + getattr(r.community.inaccurate, role)
            for r in reports
        )
        for role in RATER_ROLES
    }
    for role in RATER_ROLES:
        for i in range(1, needed[role] + 1):
            rows.append(
                {
                    "id": f"seed-{role[0]}{i:03d}",
                    "name": f"Sample {role} rater {i}",
                    "email": f"rater-{role}-{i:03d}@seed.zuula.invalid",
                    "role": role,
                    "status": "active",
                    "created_at": POOL_CREATED,
                    "email_verified_at": POOL_CREATED,
                }
            )
    await session.execute(insert(m.User), rows)
    return {u.name: u.id for u in stub_admin.SAMPLE_USERS}


async def _seed_submissions_and_reports(
    session: AsyncSession,
    users_by_name: dict[str, str],
    tracking_ids: dict[str, str],
    all_reports: list[FactCheckReportSchema],
) -> None:
    owned = {s.tracking_id: s for s in stub_account.SAMPLE_SUBMISSIONS}
    submissions, reports, annotations = [], [], []

    for r in all_reports:
        tid = tracking_ids[r.id]
        sub_type = _SUBMISSION_TYPE[r.content_type]
        mine = owned.get(r.tracking_id) if tid == r.tracking_id else None
        submitted_at = r.checked_at - timedelta(seconds=r.processing_seconds)
        submissions.append(
            {
                "tracking_id": tid,
                "user_id": SAMPLE_OWNER if mine else None,
                "channel": "web",
                "type": sub_type,
                "content": r.submitted_text if sub_type == "text" else None,
                "url": r.submitted_text if sub_type == "url" else None,
                "language": "auto",
                "preview": mine.preview if mine else r.submitted_text[:120],
                "status": "completed",
                "steps": [
                    {"step": s, "status": "done", "seconds": STEP_SECONDS[s]}
                    for s in PIPELINES[sub_type]
                ],
                "submitted_at": submitted_at,
                "completed_at": r.checked_at,
            }
        )
        reports.append(
            {
                "id": r.id,
                "tracking_id": tid,
                "title": r.title,
                "content_type": r.content_type,
                "language": r.language,
                "submitted_text": r.submitted_text,
                "source_url": r.source_url,
                "source_host": _host(r.source_url) or _citation_host(r),
                "verdict": r.verdict,
                "confidence": r.confidence,
                "summary": r.summary,
                "what_is_false": r.what_is_false,
                "what_is_true": r.what_is_true,
                "claims": [_dump(c) for c in r.claims],
                "citations": [_dump(c) for c in r.citations],
                "ai_signals": [_dump(s) for s in r.ai_signals],
                "category": r.category,
                "checked_at": r.checked_at,
                "processing_seconds": r.processing_seconds,
                "human_review": _dump(r.human_review) if r.human_review else None,
                "community_status": "standard",
            }
        )
        for a in r.annotations:
            annotations.append(
                {
                    "id": f"{r.id}-{a.id}",
                    "report_id": r.id,
                    "author_id": users_by_name[a.author],
                    "author_title": a.role,
                    "body": a.body,
                    "created_at": a.created_at,
                }
            )

    # Submissions with no report: the sample "failed" one in Amina's history.
    report_tids = {r.tracking_id for r in all_reports}
    for s in stub_account.SAMPLE_SUBMISSIONS:
        if s.tracking_id in report_tids:
            continue
        submissions.append(
            {
                "tracking_id": s.tracking_id,
                "user_id": SAMPLE_OWNER,
                "channel": "web",
                "type": s.type,
                "url": s.preview if s.type == "url" else None,
                "language": "auto",
                "preview": s.preview,
                "status": "failed" if s.status == "failed" else "processing",
                "steps": [],
                "submitted_at": s.submitted_at,
                "error": (
                    {"error": {"code": "unprocessable", "message": "We couldn't fetch that link."}}
                    if s.status == "failed"
                    else None
                ),
            }
        )

    await session.execute(insert(m.Submission), submissions)
    await session.execute(insert(m.FactCheckReport), reports)
    if annotations:
        await session.execute(insert(m.ExpertAnnotation), annotations)

    # Real reports use a separate "fc-real-*" id namespace, not this "fc-<year>-<n>" sequence
    # (app.worker.pipeline generates the next one for new submissions) — only SAMPLE_REPORTS'
    # own numbers belong in it.
    numbers = [int(r.id.rsplit("-", 1)[1]) for r in SAMPLE_REPORTS]
    await session.execute(
        text("SELECT setval('fact_check_report_number_seq', :n)"), {"n": max(numbers)}
    )


def _host(url: str | None) -> str | None:
    if not url:
        return None
    host = urlparse(url).hostname or ""
    return host.removeprefix("www.") or None


def _citation_host(r: FactCheckReportSchema) -> str | None:
    return _host(r.citations[0].url) if r.citations else None


async def _seed_ratings(
    session: AsyncSession, users_by_name: dict[str, str], all_reports: list[FactCheckReportSchema]
) -> None:
    ratings, comments = [], []
    for r in all_reports:
        votes: dict[str, tuple[str, str, datetime]] = {}  # user_id -> (vote, rater_role, at)

        for c in r.community.comments:
            uid = users_by_name[c.author]
            votes[uid] = (c.vote, c.role, c.created_at)
            comments.append(
                {
                    "id": f"{r.id}-{c.id}",
                    "report_id": r.id,
                    "user_id": uid,
                    "vote": c.vote,
                    "rater_role": c.role,
                    "body": c.body,
                    "created_at": c.created_at,
                }
            )
        for a in stub_account.SAMPLE_RATINGS:
            if a.report_id == r.id:
                votes[SAMPLE_OWNER] = (a.vote, "public", a.rated_at)

        # Fill every (vote, role) bucket up to the sample count from the rater pool.
        for vote in ("accurate", "inaccurate"):
            counts = getattr(r.community, vote)
            for role in RATER_ROLES:
                named = sum(1 for v, rr, _ in votes.values() if v == vote and rr == role)
                missing = getattr(counts, role) - named
                if missing < 0:
                    raise ValueError(f"{r.id}: more named {vote}/{role} votes than its counts")
                pool = (f"seed-{role[0]}{i:03d}" for i in range(1, 10_000))
                for uid in pool:
                    if missing == 0:
                        break
                    if uid not in votes:
                        votes[uid] = (vote, role, r.checked_at)
                        missing -= 1

        for uid, (vote, role, at) in votes.items():
            ratings.append(
                {
                    "report_id": r.id,
                    "user_id": uid,
                    "vote": vote,
                    "rater_role": role,
                    "created_at": at,
                    "updated_at": at,
                }
            )

    await session.execute(insert(m.Rating), ratings)
    await session.execute(insert(m.RatingComment), comments)

    for report in (await session.scalars(select(m.FactCheckReport))).all():
        await recompute_report_community(session, report)
        report.status_changed_at = None  # seeded state, not a transition


async def _seed_review(session: AsyncSession, users_by_name: dict[str, str]) -> None:
    # Moderation items first: user-reports cases point at them.
    content_reports, flags = [], []
    for cr in stub_admin.CONTENT_REPORTS:
        content_reports.append(
            {
                "id": cr.id,
                "report_id": cr.report_id,
                "reason": cr.reason,
                "sample": cr.sample,
                "reported_at": cr.reported_at,
            }
        )
        for i in range(1, cr.reporters + 1):
            flags.append(
                {
                    "id": f"{cr.id}-f{i}",
                    "content_report_id": cr.id,
                    "user_id": f"seed-p{i:03d}",
                    "reason": cr.reason,
                    "body": cr.sample if i == 1 else None,
                    "created_at": cr.reported_at,
                }
            )
    await session.execute(insert(m.ContentReport), content_reports)
    await session.execute(insert(m.ContentFlag), flags)
    open_reports = {cr.report_id: cr.id for cr in stub_admin.CONTENT_REPORTS}

    cases = [
        {
            "id": c.id,
            "report_id": c.report_id,
            "reason": c.reason,
            "flagged_at": c.flagged_at,
            "content_report_id": (
                open_reports.get(c.report_id) if c.reason == "user-reports" else None
            ),
            "assignee_id": users_by_name[c.assignee] if c.assignee else None,
            "priority": c.priority,
            "sla_due_at": c.sla_due_at,
            "status": "open",
        }
        for c in stub_review.SAMPLE_CASES
    ]
    # Past decisions reference cases the sample data doesn't list (rc-0412, …). Their reason
    # isn't recorded, so these decided cases are seeded as community escalations, flagged
    # `turnaround_hours` before the decision.
    decisions = []
    for d in stub_review.SAMPLE_DECISIONS:
        flagged = d.decided_at - timedelta(hours=d.turnaround_hours)
        cases.append(
            {
                "id": d.case_id,
                "report_id": d.report_id,
                "reason": "community-escalation",
                "flagged_at": flagged,
                "priority": "normal",
                "sla_due_at": flagged + timedelta(hours=rules.REVIEW_SLA_HOURS),
                "status": "decided",
                "closed_at": d.decided_at,
            }
        )
        decisions.append(
            {
                "id": d.id,
                "case_id": d.case_id,
                "report_id": d.report_id,
                "outcome": d.outcome,
                "from_verdict": d.from_verdict,
                "to_verdict": d.to,
                "justification": d.justification,
                "reviewer_id": users_by_name[d.reviewer],
                "decided_at": d.decided_at,
                "turnaround_hours": d.turnaround_hours,
            }
        )
    await session.execute(insert(m.ReviewCase), cases)
    await session.execute(insert(m.ReviewDecision), decisions)

    await session.execute(
        insert(m.ManipulationSignal),
        [
            {
                "id": s.id,
                "report_id": s.report_id,
                "pattern": s.pattern,
                "accounts": s.accounts,
                "window": s.window,
                "direction": s.direction,
                "confidence": s.confidence,
                "detected_at": SEED_NOW,
            }
            for s in stub_admin.MANIPULATION_SIGNALS
        ],
    )


async def _seed_admin(session: AsyncSession, users_by_name: dict[str, str]) -> None:
    await session.execute(
        insert(m.TrustedSource),
        [
            {
                "id": s.id,
                "name": s.name,
                "domain": s.domain,
                "type": s.type,
                "languages": s.languages,
                "tier": s.tier,
                "active": s.active,
                "last_crawled": s.last_crawled,
                "crawl_ok": s.crawl_ok,
            }
            for s in stub_admin.SAMPLE_SOURCES
        ],
    )
    await session.execute(
        insert(m.Broadcast),
        [
            {
                "id": b.id,
                "title": b.title,
                "message": b.message,
                "severity": b.severity,
                "audience": b.audience,
                "channels": b.channels,
                "sent_at": b.sent_at,
                "sent_by": users_by_name[b.sent_by],
                "reach": b.reach,
                "opened": b.opened,
            }
            for b in stub_admin.SAMPLE_BROADCASTS
        ],
    )
    await session.execute(
        insert(m.AuditLogEntry),
        [
            {
                "id": int(e.id.removeprefix("a")),
                "at": e.at,
                "actor_id": users_by_name[e.actor],
                "actor_name": e.actor,
                "actor_role": e.actor_role,
                "action": e.action,
                "target": e.target,
                "detail": e.detail,
                "ip": e.ip,
            }
            for e in stub_admin.SAMPLE_AUDIT
        ],
    )
    # Explicit ids above bypass the identity sequence; move it past them.
    await session.execute(
        text(
            "SELECT setval(pg_get_serial_sequence('audit_log', 'id'), "
            "(SELECT max(id) FROM audit_log))"
        )
    )
    await session.execute(
        insert(m.PlatformSettings),
        [{"id": 1, "settings": _dump(stub_admin.DEFAULT_SETTINGS), "updated_at": SEED_NOW}],
    )
    await session.execute(
        insert(m.ModelEvaluation),
        [
            {
                "id": f"eval-{k.id}",
                "metric": k.id,
                "value": k.value,
                "note": k.note,
                "model_version": "zuula-verify 0.3",
                "evaluated_at": SEED_NOW,
            }
            for k in stub_admin.KPIS
            if k.id in ("f1", "deepfake")
        ],
    )
    # Grace Nankya's pending accreditation (her account shows as "pending" in the admin list).
    pending = [u for u in stub_admin.SAMPLE_USERS if u.status == "pending"]
    if pending:
        await session.execute(
            insert(m.AccreditationApplication),
            [
                {
                    "id": f"acc-{u.id}",
                    "user_id": u.id,
                    "status": "pending",
                    "submitted_at": datetime.combine(u.joined, datetime.min.time(), UTC),
                }
                for u in pending
            ],
        )


async def _seed_account(session: AsyncSession) -> None:
    """The signed-in sample user's own data: sessions, notifications, alert settings, and the
    sample journalist's API keys."""
    owner = SAMPLE_OWNER
    ages = {
        "Active now": timedelta(0),
        "2 hours ago": timedelta(hours=2),
        "5 days ago": timedelta(days=5),
    }
    await session.execute(
        insert(m.Session),
        [
            {
                "id": s.id,
                "user_id": owner,
                "token_hash": _unusable_hash(),
                "device": s.device,
                "location": s.location,
                "created_at": SEED_NOW - ages[s.last_active] - timedelta(days=1),
                "last_active_at": SEED_NOW - ages[s.last_active],
                "expires_at": SEED_NOW + timedelta(seconds=rules.SESSION_TTL_REMEMBER_SECONDS),
            }
            for s in stub_account.SAMPLE_SESSIONS
        ],
    )
    await session.execute(
        insert(m.Notification),
        [
            {
                "id": n.id,
                "user_id": owner,
                "kind": n.kind,
                "title": n.title,
                "body": n.body,
                "href": n.href,
                "created_at": n.created_at,
                "read_at": n.created_at if n.read else None,
            }
            for n in stub_notifications.SAMPLE_NOTIFICATIONS
        ],
    )
    await session.execute(
        insert(m.AlertSettings),
        [
            {
                "user_id": owner,
                "settings": _dump(stub_notifications.DEFAULT_ALERT_SETTINGS),
                "updated_at": SEED_NOW,
            }
        ],
    )
    await session.execute(
        insert(m.ApiKey),
        [
            {
                "id": k.id,
                "user_id": SAMPLE_KEYS_OWNER,
                "name": k.name,
                "prefix": k.prefix,
                "secret_hash": _unusable_hash(),
                "scopes": k.scopes,
                "created_at": datetime.fromisoformat(k.created_at).replace(tzinfo=UTC),
                "last_used_at": k.last_used_at,
            }
            for k in stub_account.SAMPLE_API_KEYS
        ],
    )


async def _main() -> int:
    from app.db.session import get_engine, get_sessionmaker

    async with get_sessionmaker()() as session:
        existing = (await session.execute(select(func.count()).select_from(m.User))).scalar_one()
        if existing:
            print(f"Database already has {existing} users; not seeding. Reset it first.")
            return 1
        await seed(session)
        await session.commit()
    await get_engine().dispose()
    print(f"Seeded sample data{' plus real fact-checks' if _include_real_data() else ''}.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
