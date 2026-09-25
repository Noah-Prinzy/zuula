"use client"

import * as React from "react"
import Link from "next/link"
import {
  RiArticleLine,
  RiErrorWarningLine,
  RiFileTextLine,
  RiImageLine,
  RiLink,
  RiLoader4Line,
  RiRefreshLine,
  RiThumbDownFill,
  RiThumbUpFill,
} from "@remixicon/react"
import { useTranslations } from "next-intl"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { VerdictBadge } from "@/components/verdict/verdict-badge"
import { useRelativeTime } from "@/hooks/use-relative-time"
import { SAMPLE_RATINGS, SAMPLE_SUBMISSIONS, type ActivitySubmission } from "@/lib/mock/account"
import { cn } from "@/lib/utils"

// Labels live in Account.activity.types.<type>.
const TYPE_ICON = { text: RiFileTextLine, url: RiLink, media: RiImageLine, article: RiArticleLine }

function StatusCell({ s }: { s: ActivitySubmission }) {
  const t = useTranslations("Account.activity")
  if (s.status === "complete" && s.verdict) return <VerdictBadge verdict={s.verdict} size="sm" />
  if (s.status === "processing")
    return (
      <Badge variant="secondary" className="gap-1">
        <RiLoader4Line className="motion-safe:animate-spin" aria-hidden /> {t("checking")}
      </Badge>
    )
  return (
    <Badge variant="destructive" className="gap-1">
      <RiErrorWarningLine aria-hidden /> {t("failed")}
    </Badge>
  )
}

function Submissions() {
  const t = useTranslations("Account.activity")
  const relativeTime = useRelativeTime()
  if (SAMPLE_SUBMISSIONS.length === 0) {
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyTitle>{t("emptyTitle")}</EmptyTitle>
          <EmptyDescription>{t("emptyBody")}</EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button asChild>
            <Link href="/verify">{t("verifyClaim")}</Link>
          </Button>
        </EmptyContent>
      </Empty>
    )
  }

  return (
    <ul className="flex flex-col divide-y border bg-card">
      {SAMPLE_SUBMISSIONS.map((s) => {
        const Icon = TYPE_ICON[s.type]
        return (
          <li key={s.trackingId} className="flex flex-col gap-3 p-4 md:flex-row md:items-center">
            <Icon className="hidden size-5 shrink-0 text-muted-foreground md:block" aria-hidden />
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <p className={cn("truncate text-sm", s.type === "url" && "font-mono")}>{s.preview}</p>
              <p className="flex flex-wrap gap-x-3 text-xs text-muted-foreground">
                <span>{t(`types.${s.type}`)}</span>
                <span className="font-mono">{s.trackingId}</span>
                <time dateTime={s.submittedAt}>{relativeTime(s.submittedAt)}</time>
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <StatusCell s={s} />
              {s.reportId ? (
                <Button variant="outline" size="sm" asChild>
                  <Link href={`/fact-checks/${s.reportId}`}>{t("viewReport")}</Link>
                </Button>
              ) : (
                <Button variant="outline" size="sm" asChild>
                  <Link href={`/submissions/${s.trackingId}`}>{t("viewStatus")}</Link>
                </Button>
              )}
              {/* FR-SUBMIT-07: resubmit an updated version. */}
              <Button variant="ghost" size="sm" asChild>
                <Link href="/verify" aria-label={t("resubmitLabel", { id: s.trackingId })}>
                  <RiRefreshLine aria-hidden /> {t("resubmit")}
                </Link>
              </Button>
            </div>
          </li>
        )
      })}
    </ul>
  )
}

function Ratings() {
  const t = useTranslations("Account.activity")
  const relativeTime = useRelativeTime()
  return (
    <ul className="flex flex-col divide-y border bg-card">
      {SAMPLE_RATINGS.map((r) => {
        const accurate = r.vote === "accurate"
        const Icon = accurate ? RiThumbUpFill : RiThumbDownFill
        return (
          <li key={r.reportId} className="press-surface relative flex flex-col gap-2 p-4 [--surface-scale:1] hover:bg-muted/40 md:flex-row md:items-start">
            <div className="flex min-w-0 flex-1 flex-col gap-1.5">
              <Link href={`/fact-checks/${r.reportId}`} className="font-medium after:absolute after:inset-0 hover:text-primary">
                {r.title}
              </Link>
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <VerdictBadge verdict={r.verdict} size="sm" />
                <span className={cn("inline-flex items-center gap-1 font-medium", accurate ? "text-verdict-authentic" : "text-verdict-false")}>
                  <Icon className="size-3.5" aria-hidden />
                  {t("youRated", { vote: r.vote })}
                </span>
                <time dateTime={r.ratedAt}>{relativeTime(r.ratedAt)}</time>
              </div>
              {r.comment && <p className="border-l-2 pl-2 text-sm text-muted-foreground italic">“{r.comment}”</p>}
            </div>
          </li>
        )
      })}
    </ul>
  )
}

export function ActivityList() {
  const t = useTranslations("Account.activity")
  return (
    <Tabs defaultValue="submissions" className="gap-4">
      <TabsList>
        <TabsTrigger value="submissions">{t("submissionsTab", { count: SAMPLE_SUBMISSIONS.length })}</TabsTrigger>
        <TabsTrigger value="ratings">{t("ratingsTab", { count: SAMPLE_RATINGS.length })}</TabsTrigger>
      </TabsList>
      <TabsContent value="submissions">
        <Submissions />
      </TabsContent>
      <TabsContent value="ratings">
        <Ratings />
      </TabsContent>
    </Tabs>
  )
}
