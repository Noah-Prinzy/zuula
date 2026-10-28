"use client"

import * as React from "react"
import Link from "next/link"
import { RiArrowRightLine } from "@remixicon/react"
import { useTranslations } from "next-intl"

import { Badge } from "@/components/ui/badge"
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { VerdictBadge } from "@/components/verdict/verdict-badge"
import { useLiveData } from "@/hooks/use-live-data"
import { useFormat } from "@/lib/format"
import { SAMPLE_DECISIONS, REVIEW_SLA_HOURS } from "@/lib/mock/review"
import { getHistory, reviewApiConfigured, type ReviewDecision } from "@/lib/review-api"
import { cn } from "@/lib/utils"

type Filter = "all" | "confirmed" | "overridden"

const loadDecisions = () => getHistory().then((page) => page.data)

// FR-REVIEW-03: the reviewer's own logged decisions. Real API when configured, the sample
// decisions only in demo builds; live, a failed load shows a toast, never the samples.
export function ReviewHistory() {
  const [filter, setFilter] = React.useState<Filter>("all")
  const decisions: ReviewDecision[] = useLiveData(reviewApiConfigured(), loadDecisions, SAMPLE_DECISIONS, []).data ?? []
  const t = useTranslations("Review.history")
  const to = useTranslations("Review.outcomes")
  const f = useFormat()

  const shown = filter === "all" ? decisions : decisions.filter((d) => d.outcome === filter)
  const count = (f: Filter) => (f === "all" ? decisions.length : decisions.filter((d) => d.outcome === f).length)

  return (
    <div className="flex flex-col gap-4">
      <ToggleGroup
        type="single"
        variant="outline"
        size="sm"
        value={filter}
        onValueChange={(v) => v && setFilter(v as Filter)}
        aria-label={t("filterLabel")}
        className="w-fit"
      >
        {(["all", "confirmed", "overridden"] as const).map((v) => (
          <ToggleGroupItem key={v} value={v}>
            {t(`filters.${v}`, { count: count(v) })}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>

      {shown.length === 0 ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyTitle>{t("emptyTitle")}</EmptyTitle>
            <EmptyDescription>{t("emptyBody")}</EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <ul data-reveal="stagger" className="flex flex-col divide-y border bg-card">
          {shown.map((d) => {
            const late = d.turnaroundHours > REVIEW_SLA_HOURS
            return (
              <li key={d.id} className="flex flex-col gap-2 p-4">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <Link href={`/fact-checks/${d.reportId}`} className="font-medium hover:text-primary">
                    {d.title}
                  </Link>
                  <Badge variant={d.outcome === "overridden" ? "default" : "secondary"}>
                    {to(d.outcome)}
                  </Badge>
                </div>
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <VerdictBadge verdict={d.from} size="sm" />
                  {d.outcome === "overridden" && (
                    <>
                      <RiArrowRightLine className="size-3.5" aria-label={t("changedTo")} />
                      <VerdictBadge verdict={d.to} size="sm" />
                    </>
                  )}
                  <span className="font-mono">{d.caseId}</span>
                  <time dateTime={d.decidedAt}>
                    {f.dateTime(d.decidedAt)}
                  </time>
                  <span className={cn(late && "text-verdict-false")}>
                    {t("turnaround", { hours: d.turnaroundHours })}
                    {late && ` ${t("overSla")}`}
                  </span>
                </div>
                <p className="border-l-2 pl-3 text-sm text-muted-foreground">{d.justification}</p>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
