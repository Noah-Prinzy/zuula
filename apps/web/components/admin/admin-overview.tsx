"use client"

import { RiCheckboxCircleFill, RiErrorWarningFill } from "@remixicon/react"
import { useTranslations } from "next-intl"
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts"

import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart"
import { VerdictBadge } from "@/components/verdict/verdict-badge"
import { Skeleton } from "@/components/ui/skeleton"
import { adminApi, type AdminOverview as Overview } from "@/lib/admin-api"
import { DAILY_CHECKS, KPIS, kpiMet, SYSTEM_HEALTH, VERDICT_MIX, type Kpi } from "@/lib/mock/admin"
import { useFormat, type Format } from "@/lib/format"
import { cn } from "@/lib/utils"
import { VERDICT_META } from "@/lib/verdicts"

import { useAdminData } from "./use-admin-data"

type DailyChecks = { date: string; checks: number }[]
type VerdictMixRow = (typeof VERDICT_MIX)[number]
type HealthRow = (typeof SYSTEM_HEALTH)[number]

const DEMO: Overview = { kpis: KPIS, dailyChecks: DAILY_CHECKS, verdictMix: VERDICT_MIX, systemHealth: SYSTEM_HEALTH }

function formatKpi(f: Format, k: Kpi, v = k.value) {
  return `${f.number(v)}${k.unit}`
}

// Midday in Kampala, so the calendar day never shifts with the viewer's time zone.
function dayLabel(f: Format, iso: string) {
  return f.date(`${iso}T12:00:00+03:00`, "dayMonth")
}

// §13 KPI: a stat tile, not a chart. Status carries an icon and label, not colour alone.
function KpiTile({ kpi }: { kpi: Kpi }) {
  const t = useTranslations("Admin.overview")
  const f = useFormat()
  const met = kpiMet(kpi)
  const Icon = met ? RiCheckboxCircleFill : RiErrorWarningFill
  return (
    <div className="hover-lift flex flex-col gap-1 border bg-card p-4">
      <span className="text-xs text-muted-foreground">{t.has(`kpis.${kpi.id}` as "kpis.f1") ? t(`kpis.${kpi.id}` as "kpis.f1") : kpi.label}</span>
      <span className="font-heading text-2xl font-bold tabular-nums">{formatKpi(f, kpi)}</span>
      <span className={cn("inline-flex items-center gap-1 text-xs", met ? "text-verdict-authentic" : "text-verdict-likely-false")}>
        <Icon className="size-3.5" aria-hidden />
        {t("target", {
          status: met ? t("onTarget") : t("belowTarget"),
          direction: kpi.direction,
          value: formatKpi(f, kpi, kpi.target),
        })}
      </span>
      <span className="text-[11px] text-muted-foreground">{kpi.note}</span>
    </div>
  )
}

function ChecksChart({ days }: { days: DailyChecks }) {
  const t = useTranslations("Admin.overview")
  const f = useFormat()
  const checksConfig = { checks: { label: t("checksLabel"), color: "var(--chart-3)" } } satisfies ChartConfig
  const total = days.reduce((s, d) => s + d.checks, 0)
  return (
    <section data-reveal aria-labelledby="checks-title" className="flex flex-col gap-3 border bg-card p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="checks-title" className="font-heading text-base font-bold">
          {t("checksTitle")}
        </h2>
        <span className="text-xs text-muted-foreground">{t("checksTotal", { count: f.number(total) })}</span>
      </div>
      <ChartContainer config={checksConfig} className="h-56 w-full">
        <BarChart data={days} margin={{ left: 0, right: 0, top: 8 }}>
          <CartesianGrid vertical={false} strokeOpacity={0.5} />
          <XAxis dataKey="date" tickLine={false} axisLine={false} tickMargin={8} tickFormatter={(v) => dayLabel(f, String(v))} minTickGap={16} />
          <YAxis tickLine={false} axisLine={false} width={36} />
          <ChartTooltip cursor={{ fillOpacity: 0.3 }} content={<ChartTooltipContent labelFormatter={(v) => dayLabel(f, String(v))} />} />
          <Bar dataKey="checks" fill="var(--color-checks)" radius={[2, 2, 0, 0]} maxBarSize={32} />
        </BarChart>
      </ChartContainer>
      <details className="text-xs">
        <summary className="cursor-pointer text-muted-foreground hover:text-foreground">{t("showTable")}</summary>
        <table className="mt-2 w-full">
          <thead>
            <tr className="text-left text-muted-foreground">
              <th className="py-1 font-normal">{t("date")}</th>
              <th className="py-1 text-right font-normal">{t("checksLabel")}</th>
            </tr>
          </thead>
          <tbody>
            {days.map((d) => (
              <tr key={d.date} className="border-t">
                <td className="py-1">{dayLabel(f, d.date)}</td>
                <td className="py-1 text-right font-mono tabular-nums">{d.checks}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  )
}

// Share of verdicts: a labelled bar list (identity from the verdict badge, values in text ink).
function VerdictMix({ mix }: { mix: VerdictMixRow[] }) {
  const t = useTranslations("Admin.overview")
  const f = useFormat()
  const total = mix.reduce((s, v) => s + v.count, 0)
  return (
    <section data-reveal aria-labelledby="mix-title" className="flex flex-col gap-3 border bg-card p-4 [--d:1]">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="mix-title" className="font-heading text-base font-bold">
          {t("mixTitle")}
        </h2>
        <span className="text-xs text-muted-foreground">{t("mixTotal", { count: f.number(total) })}</span>
      </div>
      <ul className="flex flex-col gap-3">
        {mix.map((v) => {
          const pct = total ? (v.count / total) * 100 : 0
          return (
            <li key={v.verdict} className="flex flex-col gap-1">
              <div className="flex items-center justify-between gap-2 text-sm">
                <VerdictBadge verdict={v.verdict} size="sm" />
                <span className="font-mono text-xs tabular-nums">
                  {f.number(v.count)} · {f.percent(pct / 100)}
                </span>
              </div>
              <div className="h-1.5 bg-muted" aria-hidden>
                <div className={cn("bar-grow h-full", VERDICT_META[v.verdict].solid)} style={{ width: `${pct}%` }} />
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function SystemHealth({ health }: { health: HealthRow[] }) {
  const t = useTranslations("Admin.overview")
  return (
    <section data-reveal aria-labelledby="health-title" className="flex flex-col gap-3 border bg-card p-4">
      <h2 id="health-title" className="font-heading text-base font-bold">
        {t("healthTitle")}
      </h2>
      <ul className="flex flex-col divide-y">
        {health.map((h) => {
          const Icon = h.ok ? RiCheckboxCircleFill : RiErrorWarningFill
          return (
            <li key={h.label} className="flex items-center gap-3 py-2">
              <Icon className={cn("size-4 shrink-0", h.ok ? "text-verdict-authentic" : "text-verdict-likely-false")} aria-label={h.ok ? t("ok") : t("needsAttention")} />
              <span className="flex-1 text-sm">{h.label}</span>
              <span className="flex flex-col items-end">
                <span className="text-sm font-medium tabular-nums">{h.value}</span>
                <span className="text-[11px] text-muted-foreground">{h.note}</span>
              </span>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

// §13: year-one targets, checks per day, verdict mix and system health, from the API
// (GET /admin/overview) or, in demo builds, the sample numbers.
export function AdminOverview() {
  const t = useTranslations("Admin.overview")
  const { data } = useAdminData(adminApi.overview, DEMO, [])
  if (!data) return <Skeleton className="h-96 w-full" />
  const kpis = data.kpis ?? []
  const days = (data.dailyChecks ?? []).map((d) => ({ date: d.date ?? "", checks: d.checks ?? 0 }))
  const mix = (data.verdictMix ?? []) as VerdictMixRow[]
  const health = (data.systemHealth ?? []) as HealthRow[]
  const met = kpis.filter(kpiMet).length
  return (
    <div className="flex flex-col gap-8">
      <section aria-labelledby="kpi-title" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="kpi-title" className="font-heading text-lg font-bold">
            {t("targetsTitle")}
          </h2>
          <span className="text-sm text-muted-foreground">
            {t("targetsMet", { met, total: kpis.length })}
          </span>
        </div>
        <div data-reveal="stagger" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {kpis.map((k) => (
            <KpiTile key={k.id} kpi={k} />
          ))}
        </div>
      </section>

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <ChecksChart days={days} />
        <VerdictMix mix={mix} />
      </div>
      <div className="grid gap-6 xl:grid-cols-2">
        <SystemHealth health={health} />
      </div>
    </div>
  )
}
