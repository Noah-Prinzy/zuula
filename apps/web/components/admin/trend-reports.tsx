"use client"

import * as React from "react"
import { RiDownload2Line } from "@remixicon/react"
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts"
import { useTranslations } from "next-intl"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useContentLabels } from "@/hooks/use-content-labels"
import { useFormat } from "@/lib/format"
import { Skeleton } from "@/components/ui/skeleton"
import { adminApi } from "@/lib/admin-api"
import { MONTHLY_REPORTS, type MonthlyReport } from "@/lib/mock/admin"

import { useAdminData } from "./use-admin-data"

// Mid-month in Kampala, so the month never shifts with the viewer's time zone.
const midMonth = (ym: string) => `${ym}-15T12:00:00+03:00`

function download(filename: string, csv: string) {
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }))
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function toCsv(rows: MonthlyReport[]) {
  const head = "month,checks,false_or_likely_false_pct,ai_generated,top_categories,avg_delivery_seconds"
  const body = rows.map((r) => [r.month, r.checks, r.falseShare, r.aiGenerated, `"${r.topCategories.join("; ")}"`, r.avgDelivery].join(","))
  return [head, ...body].join("\n")
}

// FR-ADMIN-04: monthly misinformation trend reports.
// FR-ADMIN-05: monthly trends from the API (GET /admin/reports) or, in demo builds, the samples.
export function TrendReports() {
  const { data } = useAdminData(adminApi.monthlyReports, MONTHLY_REPORTS, [])
  if (!data) return <Skeleton className="h-96 w-full" />
  return <Trends reports={data} />
}

function Trends({ reports }: { reports: MonthlyReport[] }) {
  // A new deployment may have under two months of data; the comparison line needs both.
  const latest = reports.at(-1)
  const previous = reports.at(-2)
  const t = useTranslations("Admin.trends")
  const f = useFormat()
  const labels = useContentLabels()
  const config = { checks: { label: t("checksLabel"), color: "var(--chart-3)" } } satisfies ChartConfig
  const monthLabel = (ym: string) => f.date(midMonth(ym), "monthYear")

  return (
    <div className="flex flex-col gap-6">
      <section data-reveal aria-labelledby="trend-title" className="flex flex-col gap-3 border bg-card p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="trend-title" className="font-heading text-base font-bold">
            {t("chartTitle")}
          </h2>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              download("zuula-monthly-trends.csv", toCsv(reports))
              toast.success(t("downloaded"))
            }}
          >
            <RiDownload2Line aria-hidden /> {t("exportAll")}
          </Button>
        </div>
        <ChartContainer config={config} className="h-60 w-full">
          <BarChart data={reports} margin={{ left: 0, right: 0, top: 8 }}>
            <CartesianGrid vertical={false} strokeOpacity={0.5} />
            <XAxis dataKey="month" tickLine={false} axisLine={false} tickMargin={8} tickFormatter={(v) => f.date(midMonth(String(v)), "month")} />
            <YAxis tickLine={false} axisLine={false} width={44} tickFormatter={(v) => f.number(v)} />
            <ChartTooltip cursor={{ fillOpacity: 0.3 }} content={<ChartTooltipContent labelFormatter={(v) => monthLabel(String(v))} />} />
            <Bar dataKey="checks" fill="var(--color-checks)" radius={[2, 2, 0, 0]} maxBarSize={48} />
          </BarChart>
        </ChartContainer>
        {latest && previous && (
          <p className="text-xs text-muted-foreground">
            {t("soFar", {
              latest: monthLabel(latest.month),
              latestCount: f.number(latest.checks),
              previous: monthLabel(previous.month),
              previousCount: f.number(previous.checks),
            })}
          </p>
        )}
      </section>

      <section data-reveal aria-labelledby="months-title" className="flex flex-col gap-3 [--d:1]">
        <h2 id="months-title" className="font-heading text-lg font-bold">
          {t("monthlyTitle")}
        </h2>
        <div className="overflow-x-auto border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("columns.month")}</TableHead>
                <TableHead className="text-right">{t("columns.checks")}</TableHead>
                <TableHead className="text-right">{t("columns.false")}</TableHead>
                <TableHead className="text-right">{t("columns.ai")}</TableHead>
                <TableHead>{t("columns.topics")}</TableHead>
                <TableHead className="text-right">{t("columns.time")}</TableHead>
                <TableHead>
                  <span className="sr-only">{t("columns.export")}</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {[...reports].reverse().map((r) => (
                <TableRow key={r.month}>
                  <TableCell className="font-medium whitespace-nowrap">{monthLabel(r.month)}</TableCell>
                  <TableCell className="text-right font-mono tabular-nums">{f.number(r.checks)}</TableCell>
                  <TableCell className="text-right font-mono tabular-nums">{r.falseShare}%</TableCell>
                  <TableCell className="text-right font-mono tabular-nums">{f.number(r.aiGenerated)}</TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {r.topCategories.map((c) => (
                        <Badge key={c} variant="outline">{labels.category(c)}</Badge>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums">{r.avgDelivery}s</TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="xs"
                      onClick={() => {
                        download(`zuula-report-${r.month}.csv`, toCsv([r]))
                        toast.success(t("monthDownloaded", { month: monthLabel(r.month) }))
                      }}
                    >
                      <RiDownload2Line aria-hidden /> {t("csv")}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        <p className="text-xs text-muted-foreground">
          {t("pdfNote")}
        </p>
      </section>
    </div>
  )
}
