import type { Metadata } from "next"
import Link from "next/link"
import { notFound } from "next/navigation"
import { RiArrowLeftLine, RiFlaskLine } from "@remixicon/react"
import { getTranslations } from "next-intl/server"
import { PageSheet } from "@/components/decor/page-sheet"

import { CommunityStatusBanner } from "@/components/community/community-status"
import { RatingComments } from "@/components/community/rating-comments"
import { RatingPanel } from "@/components/community/rating-panel"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { AISignalsList } from "@/components/verdict/ai-signals-list"
import { CitationCard } from "@/components/verdict/citation-card"
import { ClaimHighlighter } from "@/components/verdict/claim-highlighter"
import { ExpertAnnotation } from "@/components/verdict/expert-annotation"
import { FactCheckCard } from "@/components/verdict/fact-check-card"
import { ReportActionBar } from "@/components/verdict/report-action-bar"
import { VerdictSummary } from "@/components/verdict/verdict-summary"
import { WhatIsTrueCard } from "@/components/verdict/what-is-true-card"
import { communityScore } from "@/lib/community"
import {
  factChecksApiConfigured,
  fetchAllReportsForLibrary,
  fetchFullReport,
  fetchRelated,
} from "@/lib/fact-checks-api"
import { relatedReports } from "@/lib/library"
import { getSampleReport, SAMPLE_REPORTS } from "@/lib/mock/fact-checks"
import type { FactCheckReport } from "@/lib/types/fact-check"

type Props = { params: Promise<{ id: string }> }

// Real data when the API is configured, the sample report otherwise or if the id isn't a real
// one (404s and network errors both fall back, same "demo when unconfigured" pattern as the
// rest of these pages) — getSampleReport() never fails, so this always resolves to a report or
// null, never throws.
async function loadReport(id: string): Promise<FactCheckReport | null> {
  if (factChecksApiConfigured()) {
    try {
      const report = await fetchFullReport(id)
      if (report) return report
    } catch {
      // Fall through to the sample report below.
    }
  }
  return getSampleReport(id) ?? null
}

async function loadRelated(id: string, report: FactCheckReport): Promise<FactCheckReport[]> {
  if (factChecksApiConfigured()) {
    try {
      return await fetchRelated(id, 3)
    } catch {
      // Fall through to the sample-data relation below.
    }
  }
  return relatedReports(SAMPLE_REPORTS, report, 3)
}

// The [locale] layout sets dynamicParams = false (only 5 known locales should ever match), and
// Next computes that per route as the AND of every segment's own setting — a descendant can't
// override an ancestor's false back to true. So a real id has to come out of this function
// too, or it 404s like any other unlisted id, same as it would under the sample-only set.
export async function generateStaticParams() {
  const ids = SAMPLE_REPORTS.map((r) => r.id)
  if (factChecksApiConfigured()) {
    try {
      const { reports } = await fetchAllReportsForLibrary()
      ids.push(...reports.map((r) => r.id))
    } catch {
      // Build/dev without a reachable API: the sample ids are still enough to render.
    }
  }
  return ids.map((id) => ({ id }))
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const report = await loadReport((await params).id)
  const t = await getTranslations("Report")
  if (!report) return { title: t("metaFallback") }
  const tv = await getTranslations("Verdicts.labels")
  return {
    title: t("metaTitle", { verdict: tv(report.verdict), title: report.title }),
    description: report.summary,
  }
}

function Section({
  id,
  title,
  description,
  children,
}: {
  id: string
  title: string
  description?: string
  children: React.ReactNode
}) {
  return (
    <section data-reveal aria-labelledby={id} className="flex flex-col gap-3">
      <div>
        <h2 id={id} className="font-heading text-lg font-bold">
          {title}
        </h2>
        {description && <p className="text-sm text-muted-foreground">{description}</p>}
      </div>
      {children}
    </section>
  )
}

export default async function ReportPage({ params }: Props) {
  const id = (await params).id
  const report = await loadReport(id)
  if (!report) notFound()
  const community = communityScore(report.community)
  const related = await loadRelated(id, report)
  const t = await getTranslations("Related")
  const tr = await getTranslations("Report")
  const tc = await getTranslations("Common")

  return (
    <PageSheet className="md:mt-10">
    <div className="page-container flex flex-col gap-6 py-8">
      {/* Phones use the app bar's back button instead. */}
      <div className="flex items-center justify-between gap-4 max-md:hidden">
        <Button variant="ghost" size="sm" asChild className="-ml-2">
          <Link href="/fact-checks">
            <RiArrowLeftLine aria-hidden /> {tr("backToLibrary")}
          </Link>
        </Button>
      </div>

      {!report.id.startsWith("fc-real-") && (
        <Alert className="enter">
          <RiFlaskLine aria-hidden />
          <AlertTitle>{tc("sampleReportTitle")}</AlertTitle>
          <AlertDescription>
            {tc("sampleReportBody")}
          </AlertDescription>
        </Alert>
      )}

      <VerdictSummary report={report} className="enter [--d:1]" />
      <CommunityStatusBanner status={community.status} className="enter [--d:2]" />

      <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_22rem] xl:grid-cols-[minmax(0,1fr)_26rem]">
        {/* Two columns of sections on very wide screens so lines stay readable. */}
        <div className="grid items-start gap-8 2xl:grid-cols-2">
          <Section
            id="submitted"
            title={tr("checked")}
            description={
              report.claims.length > 0
                ? tr("checkedHint")
                : undefined
            }
          >
            <div className="border bg-card p-4">
              <ClaimHighlighter
                text={report.submittedText}
                claims={report.claims}
                citations={report.citations}
              />
            </div>
          </Section>

          <Section id="findings" title={tr("findings")}>
            <WhatIsTrueCard whatIsFalse={report.whatIsFalse} whatIsTrue={report.whatIsTrue} />
          </Section>

          {report.aiSignals.length > 0 && (
            <Section
              id="ai-signals"
              title={tr("signals")}
              description={tr("signalsHint")}
            >
              <AISignalsList signals={report.aiSignals} />
            </Section>
          )}

          <Section
            id="comments"
            title={tr("comments")}
            description={tr("commentsHint")}
          >
            <RatingComments comments={report.community.comments} />
          </Section>

          {report.annotations.length > 0 && (
            <Section id="expert-notes" title={tr("expertNotes")}>
              <div className="flex flex-col gap-3">
                {report.annotations.map((a) => (
                  <ExpertAnnotation key={a.id} annotation={a} />
                ))}
              </div>
            </Section>
          )}
        </div>

        <aside className="flex flex-col gap-8">
          <Section id="rating" title={tr("rating")}>
            <RatingPanel initial={report.community} />
          </Section>

          <Section
            id="sources"
            title={tr("sources")}
            description={tr("sourcesHint", { count: report.citations.length })}
          >
            <div className="flex flex-col gap-2">
              {report.citations.map((c, i) => (
                <CitationCard key={c.id} citation={c} index={i + 1} />
              ))}
            </div>
          </Section>
        </aside>
      </div>

      {/* FR-SEARCH-03: related fact-checks. */}
      {related.length > 0 && (
        <Section id="related" title={t("title")} description={t("description")}>
          <ul className="grid gap-4 max-md:bleed max-md:gap-0 max-md:border-t md:grid-cols-2 xl:grid-cols-3">
            {related.map((r) => (
              <li key={r.id} className="hover-lift">
                <FactCheckCard report={r} feed />
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
    <ReportActionBar title={report.title} sources={report.citations.length} />
    </PageSheet>
  )
}
