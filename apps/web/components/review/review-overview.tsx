"use client"

import * as React from "react"
import Link from "next/link"
import { RiArrowRightLine } from "@remixicon/react"
import { useTranslations } from "next-intl"

import { useSession } from "@/components/providers/session-provider"
import {
  ReasonBadge,
  SlaBadge,
  StatCard,
} from "@/components/review/review-badges"
import { Button } from "@/components/ui/button"
import { VerdictBadge } from "@/components/verdict/verdict-badge"
import { fetchFullReport } from "@/lib/fact-checks-api"
import { SAMPLE_REPORTS } from "@/lib/mock/fact-checks"
import { useLiveData } from "@/hooks/use-live-data"
import { useRelativeTime } from "@/hooks/use-relative-time"
import { useFormat } from "@/lib/format"
import {
  REASON_META,
  REVIEW_SLA_HOURS,
  SAMPLE_CASES,
  SAMPLE_DECISIONS,
  type ReviewReason,
} from "@/lib/mock/review"
import {
  dueAtFor,
  getHistory,
  getOverview,
  getQueue,
  hoursLeftFor,
  reviewApiConfigured,
  type ReviewCase,
  type ReviewDecision,
} from "@/lib/review-api"
import type { FactCheckReport } from "@/lib/types/fact-check"

type State = {
  queueSize: number
  overdue: number
  dueSoon: number
  cases: ReviewCase[]
  reports: Map<string, FactCheckReport>
  decisions: ReviewDecision[]
}

const EMPTY_STATE: State = { queueSize: 0, overdue: 0, dueSoon: 0, cases: [], reports: new Map(), decisions: [] }

async function loadState(): Promise<State> {
  const [overview, queue, history] = await Promise.all([getOverview(), getQueue({ perPage: 100 }), getHistory()])
  // Not fetchAllReportsForLibrary(): that's the public listing, which excludes suspended
  // reports (app/services/reports.py's LISTED) — exactly the kind of report a review case is
  // often open about. Fetch each case's report directly instead (GET /fact-checks/{id} always
  // serves it, suspended or not).
  const fetched = await Promise.all(queue.data.map((c) => fetchFullReport(c.reportId).catch(() => null)))
  return {
    queueSize: overview.queueSize,
    overdue: overview.overdue,
    dueSoon: overview.dueSoon,
    cases: queue.data,
    reports: new Map(fetched.filter((r): r is FactCheckReport => r !== null).map((r) => [r.id, r])),
    decisions: history.data,
  }
}

function sampleState(): State {
  return {
    queueSize: SAMPLE_CASES.length,
    overdue: SAMPLE_CASES.filter((c) => hoursLeftFor(dueAtFor(c)) < 0).length,
    dueSoon: SAMPLE_CASES.filter((c) => {
      const h = hoursLeftFor(dueAtFor(c))
      return h >= 0 && h < 12
    }).length,
    cases: SAMPLE_CASES,
    reports: new Map(SAMPLE_REPORTS.map((r) => [r.id, r])),
    decisions: SAMPLE_DECISIONS,
  }
}

export function ReviewOverview() {
  const { user } = useSession()
  const live = reviewApiConfigured()
  // Sample data only in demo builds; live, empty until loaded and a toast if it fails.
  const [demo] = React.useState(() => (live ? EMPTY_STATE : sampleState()))
  const state = useLiveData(live, loadState, demo, []).data ?? EMPTY_STATE
  const t = useTranslations("Review.overview")
  const tr = useTranslations("Review.reasons")
  const to = useTranslations("Review.outcomes")
  const f = useFormat()
  const relativeTime = useRelativeTime()

  const withSla = state.cases
    .map((c) => ({ ...c, hoursLeft: hoursLeftFor(dueAtFor(c)) }))
    .sort((a, b) => a.hoursLeft - b.hoursLeft)
  // getHistory() is already "my decisions" server-side; the sample data isn't, so it still
  // needs the name filter.
  const mine = live
    ? state.decisions
    : state.decisions.filter((d) => d.reviewer === user?.name)
  const avgTurnaround = mine.length
    ? mine.reduce((s, d) => s + d.turnaroundHours, 0) / mine.length
    : null
  const byReason = (Object.keys(REASON_META) as ReviewReason[]).map((r) => ({
    reason: r,
    count: state.cases.filter((c) => c.reason === r).length,
  }))
  const max = Math.max(1, ...byReason.map((b) => b.count))

  return (
    <div className="flex flex-col gap-8">
      <div
        data-reveal="stagger"
        className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"
      >
        <StatCard
          label={t("inQueue")}
          value={state.queueSize}
          hint={t("unassignedCount", {
            count: state.cases.filter((c) => !c.assignee).length,
          })}
        />
        <StatCard
          label={t("overdue")}
          value={state.overdue}
          tone={state.overdue ? "danger" : "good"}
          hint={t("overdueHint", { hours: REVIEW_SLA_HOURS })}
        />
        <StatCard
          label={t("dueSoon")}
          value={state.dueSoon}
          tone={state.dueSoon ? "warning" : "default"}
        />
        <StatCard
          label={t("avgTurnaround")}
          value={
            avgTurnaround === null
              ? "—"
              : t("hours", {
                  value: f.number(avgTurnaround, {
                    minimumFractionDigits: 1,
                    maximumFractionDigits: 1,
                  }),
                })
          }
          tone={
            avgTurnaround !== null && avgTurnaround <= REVIEW_SLA_HOURS
              ? "good"
              : "default"
          }
          hint={t("decisionsSoFar", { count: mine.length })}
        />
      </div>

      <div className="grid items-start gap-8 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <section
          data-reveal
          aria-labelledby="attention"
          className="flex flex-col gap-3 [--d:2]"
        >
          <div className="flex items-end justify-between gap-2">
            <h2 id="attention" className="font-heading text-lg font-bold">
              {t("needsAttention")}
            </h2>
            <Button variant="outline" size="sm" asChild>
              <Link href="/review/queue">
                {t("fullQueue")} <RiArrowRightLine aria-hidden />
              </Link>
            </Button>
          </div>
          <ul className="flex flex-col divide-y border bg-card">
            {withSla
              .filter((c) => state.reports.has(c.reportId))
              .slice(0, 4)
              .map((c) => {
                const report = state.reports.get(c.reportId)!
                return (
                  <li
                    key={c.id}
                    className="press-surface relative flex flex-col gap-2 p-4 [--surface-scale:1] hover:bg-muted/40 md:flex-row md:items-center"
                  >
                    <div className="flex min-w-0 flex-1 flex-col gap-1">
                      <Link
                        href={`/review/cases/${c.id}`}
                        className="font-medium after:absolute after:inset-0 hover:text-primary"
                      >
                        {report.title}
                      </Link>
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                        <VerdictBadge verdict={report.verdict} size="sm" />
                        <ReasonBadge reason={c.reason} reports={c.reports} />
                        <span className="text-xs text-muted-foreground">
                          {c.assignee
                            ? c.assignee === user?.name
                              ? t("assignedToYou")
                              : t("assignedTo", { name: c.assignee })
                            : t("unassigned")}
                        </span>
                      </div>
                    </div>
                    <SlaBadge dueAt={dueAtFor(c)} />
                  </li>
                )
              })}
          </ul>
        </section>

        <div className="flex flex-col gap-8">
          <section
            data-reveal
            aria-labelledby="by-reason"
            className="flex flex-col gap-3 [--d:3]"
          >
            <h2 id="by-reason" className="font-heading text-lg font-bold">
              {t("byReason")}
            </h2>
            <ul className="flex flex-col gap-3 border bg-card p-4">
              {byReason.map((b) => (
                <li key={b.reason} className="flex flex-col gap-1">
                  <div className="flex justify-between text-sm">
                    <span>{tr(`${b.reason}.label`)}</span>
                    <span className="font-mono tabular-nums">{b.count}</span>
                  </div>
                  <div className="h-1.5 bg-muted" aria-hidden>
                    <div
                      className="bar-grow h-full bg-primary"
                      style={{ width: `${(b.count / max) * 100}%` }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          </section>

          <section
            data-reveal
            aria-labelledby="recent"
            className="flex flex-col gap-3 [--d:4]"
          >
            <h2 id="recent" className="font-heading text-lg font-bold">
              {t("recent")}
            </h2>
            {mine.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {t("recentEmpty")}
              </p>
            ) : (
              <ul className="flex flex-col divide-y border bg-card">
                {mine.slice(0, 3).map((d) => (
                  <li key={d.id} className="flex flex-col gap-1 p-3 text-sm">
                    <span className="line-clamp-1 font-medium">{d.title}</span>
                    <span className="text-xs text-muted-foreground">
                      {to(d.outcome)} · {relativeTime(d.decidedAt)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <Button variant="link" className="h-auto w-fit p-0" asChild>
              <Link href="/review/history">{t("allDecisions")}</Link>
            </Button>
          </section>
        </div>
      </div>
    </div>
  )
}
