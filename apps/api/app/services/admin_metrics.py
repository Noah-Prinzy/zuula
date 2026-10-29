"""The admin Overview and monthly Reports (FR-ADMIN-01, FR-ADMIN-08), computed from platform
data. The targets and labels are the spec's year-one KPIs (§13), as the admin screen shows
them (apps/web/lib/mock/admin.ts's KPIS).

Two KPIs can't be derived from platform data — text-detection F1 and deepfake accuracy come
from model evaluation runs, stored in `model_evaluations` (P4 writes them; seeded until then).
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ApiKey,
    FactCheckReport,
    ModelEvaluation,
    ReviewDecision,
    Submission,
    TrustedSource,
    User,
)
from app.db.models.identity import LOCALES
from app.schemas.admin import (
    AdminOverview,
    DailyCheckPoint,
    Kpi,
    MonthlyReport,
    SystemHealthItem,
    VerdictCount,
)
from app.services import provider_health

_KAMPALA = "Africa/Kampala"
_LOCAL_DAY = func.date(func.timezone(_KAMPALA, FactCheckReport.checked_at))
_TOTAL_RATINGS = (
    FactCheckReport.accurate_public
    + FactCheckReport.accurate_journalist
    + FactCheckReport.accurate_expert
    + FactCheckReport.inaccurate_public
    + FactCheckReport.inaccurate_journalist
    + FactCheckReport.inaccurate_expert
)

# §13 year-one targets: (id, label, unit, target, direction).
KPI_TARGETS = [
    ("f1", "Text detection F1", "%", 90, "min"),
    ("deepfake", "Deepfake accuracy", "%", 85, "min"),
    ("mau", "Monthly active users", "", 50_000, "min"),
    ("latency", "Avg text verdict time", "s", 10, "max"),
    ("ratings", "Ratings per verdict", "", 25, "min"),
    ("turnaround", "Expert turnaround", "h", 48, "max"),
    ("partners", "API partners", "", 10, "min"),
    ("languages", "Languages supported", "", 5, "min"),
]
_VERDICTS = ("false", "likely-false", "authentic", "ai-generated", "unverifiable")


async def _scalar(db: AsyncSession, query, default=0):
    value = (await db.execute(query)).scalar_one_or_none()
    return default if value is None else value


async def _kpi_values(db: AsyncSession, now: datetime) -> dict[str, tuple[float, str]]:
    month_ago = now - timedelta(days=30)
    week_ago = now - timedelta(days=7)
    values: dict[str, tuple[float, str]] = {}

    for metric in ("f1", "deepfake"):
        ev = (
            await db.scalars(
                select(ModelEvaluation)
                .where(ModelEvaluation.metric == metric)
                .order_by(ModelEvaluation.evaluated_at.desc())
                .limit(1)
            )
        ).first()
        values[metric] = (ev.value, ev.note) if ev else (0, "No evaluation run yet")

    mau = await _scalar(
        db,
        select(func.count()).where(User.last_active_at >= month_ago, User.deleted_at.is_(None)),
    )
    values["mau"] = (mau, "Signed-in users active in the last 30 days")

    latency = await _scalar(
        db,
        select(func.percentile_cont(0.5).within_group(FactCheckReport.processing_seconds)).where(
            FactCheckReport.content_type == "text", FactCheckReport.checked_at >= week_ago
        ),
        None,
    )
    values["latency"] = (
        (round(latency, 1), "p50 over the last 7 days")
        if latency is not None
        else (0, "No text checks in the last 7 days")
    )

    per_verdict = await _scalar(
        db,
        select(func.avg(_TOTAL_RATINGS)).where(FactCheckReport.checked_at >= month_ago),
        None,
    )
    values["ratings"] = (
        round(float(per_verdict), 1) if per_verdict is not None else 0,
        "Mean over the last 30 days",
    )

    turnaround = await _scalar(
        db,
        select(func.avg(ReviewDecision.turnaround_hours)).where(
            ReviewDecision.decided_at >= month_ago
        ),
        None,
    )
    values["turnaround"] = (
        round(float(turnaround), 1) if turnaround is not None else 0,
        "Mean, last 30 days",
    )

    partners = await _scalar(
        db,
        select(func.count(func.distinct(ApiKey.user_id))).where(ApiKey.revoked_at.is_(None)),
    )
    values["partners"] = (partners, "Accounts with an active API key")
    values["languages"] = (len(LOCALES), "English, Luganda, Acholi, Runyankole, Ateso")
    return values


async def overview(db: AsyncSession) -> AdminOverview:
    now = datetime.now(UTC)
    values = await _kpi_values(db, now)
    kpis = [
        Kpi(
            id=kpi_id,
            label=label,
            value=values[kpi_id][0],
            unit=unit,
            target=target,
            direction=direction,
            note=values[kpi_id][1],
        )
        for kpi_id, label, unit, target, direction in KPI_TARGETS
    ]

    # Checks per day for the last 14 Uganda days (UTC+3, no DST), zero-filled.
    today = (now + timedelta(hours=3)).date()
    start = today - timedelta(days=13)
    counts = dict(
        (
            await db.execute(
                select(_LOCAL_DAY, func.count()).where(start <= _LOCAL_DAY).group_by(_LOCAL_DAY)
            )
        ).all()
    )
    daily = [
        DailyCheckPoint(
            date=start + timedelta(days=i), checks=counts.get(start + timedelta(days=i), 0)
        )
        for i in range(14)
    ]

    mix = dict(
        (
            await db.execute(
                select(FactCheckReport.verdict, func.count()).group_by(FactCheckReport.verdict)
            )
        ).all()
    )
    verdict_mix = [VerdictCount(verdict=v, count=mix.get(v, 0)) for v in _VERDICTS]

    return AdminOverview(
        kpis=kpis,
        daily_checks=daily,
        verdict_mix=verdict_mix,
        system_health=await _system_health(db, now),
    )


async def _system_health(db: AsyncSession, now: datetime) -> list[SystemHealthItem]:
    waiting = (
        await db.execute(
            select(func.count(), func.min(Submission.submitted_at)).where(
                Submission.status.in_(("queued", "processing"))
            )
        )
    ).one()
    queued, oldest = waiting
    oldest_s = int((now - oldest).total_seconds()) if oldest else 0
    # A submission still waiting after 10 minutes means the worker isn't keeping up.
    queue_ok = oldest_s < 600

    model = (
        await db.scalars(
            select(ModelEvaluation).order_by(ModelEvaluation.evaluated_at.desc()).limit(1)
        )
    ).first()

    failing = await _scalar(
        db,
        select(func.count()).where(
            TrustedSource.active.is_(True), TrustedSource.crawl_ok.is_(False)
        ),
    )
    return [
        SystemHealthItem(label="Database", value="Connected", ok=True, note="PostgreSQL"),
        SystemHealthItem(
            label="Analysis queue",
            value=f"{queued} job{'s' if queued != 1 else ''}",
            ok=queue_ok,
            note=f"Oldest {oldest_s} s" if queued else "Nothing waiting",
        ),
        SystemHealthItem(
            label="AI model",
            value=(model.model_version or "Unknown") if model else "Not evaluated",
            ok=model is not None,
            note=f"Evaluated {model.evaluated_at:%d %b}" if model else "No evaluation run yet",
        ),
        SystemHealthItem(
            label="Source crawler",
            value=f"{failing} source{'s' if failing != 1 else ''} failing" if failing else "All OK",
            ok=failing == 0,
            note="See Sources" if failing else "Active sources crawled",
        ),
        # Milestone D6: each hosted AI service's last answer or failure.
        *await provider_health.status_items(),
    ]


async def monthly_reports(db: AsyncSession, months: int = 6) -> list[MonthlyReport]:
    """FR-ADMIN-08: one row per month with checks, newest last (the admin chart's order)."""
    month = func.to_char(func.timezone(_KAMPALA, FactCheckReport.checked_at), "YYYY-MM")
    rows = (
        await db.execute(
            select(
                month,
                func.count(),
                func.avg(cast(FactCheckReport.verdict.in_(("false", "likely-false")), Integer))
                * 100,
                func.sum(cast(FactCheckReport.verdict == "ai-generated", Integer)),
                func.avg(FactCheckReport.processing_seconds),
            )
            .group_by(month)
            .order_by(month.desc())
            .limit(months)
        )
    ).all()
    reports = []
    for ym, checks, false_share, ai, avg_delivery in reversed(rows):
        top = await db.scalars(
            select(FactCheckReport.category)
            .where(month == ym)
            .group_by(FactCheckReport.category)
            .order_by(func.count().desc(), FactCheckReport.category)
            .limit(3)
        )
        reports.append(
            MonthlyReport(
                month=ym,
                checks=checks,
                false_share=round(float(false_share or 0), 1),
                ai_generated=ai or 0,
                top_categories=list(top),
                avg_delivery=round(float(avg_delivery or 0), 1),
            )
        )
    return reports
