"use client"

import * as React from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { RiFileList3Line, RiShieldUserLine } from "@remixicon/react"
import { useTranslations } from "next-intl"
import { toast } from "sonner"

import { CCSMeter } from "@/components/community/ccs-meter"
import { CommunityStatusBanner } from "@/components/community/community-status"
import { useSession } from "@/components/providers/session-provider"
import { ReasonBadge, SlaBadge } from "@/components/review/review-badges"
import { startNavigationProgress } from "@/components/shell/route-progress"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { AISignalsList } from "@/components/verdict/ai-signals-list"
import { CitationCard } from "@/components/verdict/citation-card"
import { ClaimHighlighter } from "@/components/verdict/claim-highlighter"
import { VerdictBadge } from "@/components/verdict/verdict-badge"
import { VerdictSummary } from "@/components/verdict/verdict-summary"
import { WhatIsTrueCard } from "@/components/verdict/what-is-true-card"
import { communityScore, RATING_WEIGHTS } from "@/lib/community"
import type { ReviewCase } from "@/lib/mock/review"
import { VERDICTS, type FactCheckReport, type RaterRole, type Verdict } from "@/lib/types/fact-check"
import { cn } from "@/lib/utils"

const MIN_JUSTIFICATION = 30
const MIN_REASON = 10

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section data-reveal aria-labelledby={id} className="flex flex-col gap-3">
      <h2 id={id} className="font-heading text-lg font-bold">
        {title}
      </h2>
      {children}
    </section>
  )
}

function CommunitySignals({ report }: { report: FactCheckReport }) {
  const score = communityScore(report.community)
  const roles: RaterRole[] = ["public", "journalist", "expert"]
  const t = useTranslations("Review.case")
  const tRoles = useTranslations("Roles")
  return (
    <div className="flex flex-col gap-4 border bg-card p-4">
      <h2 className="font-heading text-sm font-bold">{t("communitySignals")}</h2>
      <CCSMeter score={score} />
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="whitespace-normal">{t("rater")}</TableHead>
            <TableHead className="text-right whitespace-normal">{t("accurate")}</TableHead>
            <TableHead className="text-right whitespace-normal">{t("inaccurate")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {roles.map((r) => (
            <TableRow key={r}>
              <TableCell className="text-xs">
                {tRoles(r)} <span className="text-muted-foreground">· {RATING_WEIGHTS[r]}×</span>
              </TableCell>
              <TableCell className="text-right font-mono tabular-nums">{report.community.accurate[r]}</TableCell>
              <TableCell className="text-right font-mono tabular-nums">{report.community.inaccurate[r]}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {report.community.comments.length > 0 && (
        <ul className="flex flex-col gap-2 border-t pt-3">
          {report.community.comments.slice(0, 3).map((c) => (
            <li key={c.id} className="text-xs">
              <span className={cn("font-medium", c.vote === "accurate" ? "text-verdict-authentic" : "text-verdict-false")}>
                {c.vote === "accurate" ? t("accurate") : t("inaccurate")}
              </span>{" "}
              · {c.author}: <span className="text-muted-foreground">“{c.body}”</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

type Decision = "confirm" | "override"

// FR-REVIEW-02 to 05: confirm or override the AI verdict with a logged justification.
function DecisionForm({ report, caseId }: { report: FactCheckReport; caseId: string }) {
  const router = useRouter()
  const { user } = useSession()
  const [decision, setDecision] = React.useState<Decision>("confirm")
  const [verdict, setVerdict] = React.useState<Verdict | null>(null)
  const [justification, setJustification] = React.useState("")
  const [note, setNote] = React.useState("")
  const [publishNote, setPublishNote] = React.useState(true)
  const [errors, setErrors] = React.useState<Record<string, string>>({})
  const [confirmOpen, setConfirmOpen] = React.useState(false)
  const t = useTranslations("Review.case")
  const tc = useTranslations("Common")

  const finalVerdict = decision === "confirm" ? report.verdict : verdict

  function validate(e: React.FormEvent) {
    e.preventDefault()
    const next: Record<string, string> = {}
    if (decision === "override" && !verdict) next.verdict = t("errors.verdict")
    if (decision === "override" && justification.trim().length < MIN_JUSTIFICATION)
      next.justification = t("errors.overrideShort", { min: MIN_JUSTIFICATION })
    if (decision === "confirm" && justification.trim().length < MIN_REASON)
      next.justification = t("errors.confirmShort", { min: MIN_REASON })
    setErrors(next)
    if (Object.keys(next).length === 0) setConfirmOpen(true)
  }

  function submit() {
    toast.success(decision === "confirm" ? t("confirmedToast") : t("overriddenToast"), {
      description: t("loggedAs", { caseId, name: user?.name ?? t("yourName") }),
    })
    startNavigationProgress()
    router.push("/review/queue")
  }

  return (
    <form noValidate onSubmit={validate} className="flex flex-col gap-4 border bg-card p-4">
      <h2 className="font-heading text-sm font-bold">{t("yourDecision")}</h2>

      <RadioGroup value={decision} onValueChange={(v) => setDecision(v as Decision)} className="gap-2">
        {(
          [
            { value: "confirm", label: t("confirmOption"), hint: <VerdictBadge verdict={report.verdict} size="sm" /> },
            { value: "override", label: t("overrideOption"), hint: <span className="text-xs text-muted-foreground">{t("chooseCorrect")}</span> },
          ] as const
        ).map((o) => (
          <label
            key={o.value}
            htmlFor={`decision-${o.value}`}
            className="flex cursor-pointer items-center gap-3 border p-3 has-[[data-state=checked]]:border-primary/50 has-[[data-state=checked]]:bg-primary/5"
          >
            <RadioGroupItem id={`decision-${o.value}`} value={o.value} />
            <span className="flex flex-1 flex-col gap-1">
              <span className="text-sm font-medium">{o.label}</span>
              {o.hint}
            </span>
          </label>
        ))}
      </RadioGroup>

      {decision === "override" && (
        <Field data-invalid={!!errors.verdict}>
          <FieldLabel>{t("correctVerdict")}</FieldLabel>
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label={t("correctVerdict")}>
            {VERDICTS.filter((v) => v !== report.verdict).map((v) => (
              <button
                key={v}
                type="button"
                role="radio"
                aria-checked={verdict === v}
                onClick={() => setVerdict(v)}
                className={cn(
                  "press border p-1 outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  verdict === v ? "border-foreground" : "border-transparent opacity-70 hover:opacity-100"
                )}
              >
                <VerdictBadge verdict={v} size="sm" />
              </button>
            ))}
          </div>
          {errors.verdict && <FieldError>{errors.verdict}</FieldError>}
        </Field>
      )}

      <Field data-invalid={!!errors.justification}>
        <FieldLabel htmlFor="justification">
          {t("justification")} {decision === "override" && <span className="text-destructive">{t("required")}</span>}
        </FieldLabel>
        <Textarea
          id="justification"
          rows={4}
          value={justification}
          onChange={(e) => setJustification(e.target.value)}
          placeholder={t("justificationPlaceholder")}
          aria-invalid={!!errors.justification}
        />
        <FieldDescription>{t("justificationHint")}</FieldDescription>
        {errors.justification && <FieldError>{errors.justification}</FieldError>}
      </Field>

      <Field>
        <FieldLabel htmlFor="public-note">{t("publicNote")}</FieldLabel>
        <Textarea
          id="public-note"
          rows={3}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder={t("publicNotePlaceholder")}
        />
        <div className="flex items-center gap-2">
          <Checkbox id="publish-note" checked={publishNote} onCheckedChange={(c) => setPublishNote(c === true)} />
          <label htmlFor="publish-note" className="text-xs text-muted-foreground">
            {t("showOnReport")}
          </label>
        </div>
      </Field>

      <div className="flex flex-wrap gap-2">
        <Button type="submit">{t("submitDecision")}</Button>
        <Button type="button" variant="ghost" asChild>
          <Link href="/review/queue">{t("backToQueue")}</Link>
        </Button>
      </div>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{decision === "confirm" ? t("confirmTitle") : t("overrideTitle")}</AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="flex flex-col gap-3">
                <span className="flex flex-wrap items-center gap-2">
                  <VerdictBadge verdict={report.verdict} size="sm" />
                  {decision === "override" && finalVerdict && (
                    <>
                      <span aria-hidden>→</span>
                      <VerdictBadge verdict={finalVerdict} size="sm" />
                    </>
                  )}
                </span>
                <span>{t("confirmBody")}</span>
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{tc("goBack")}</AlertDialogCancel>
            <AlertDialogAction onClick={submit}>{t("submit")}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </form>
  )
}

export function CaseReview({ reviewCase, report }: { reviewCase: ReviewCase; report: FactCheckReport }) {
  const score = communityScore(report.community)
  const t = useTranslations("Review")
  const tRep = useTranslations("Report")

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="font-mono text-sm">{reviewCase.id}</span>
        <ReasonBadge reason={reviewCase.reason} reports={reviewCase.reports} />
        <SlaBadge flaggedAt={reviewCase.flaggedAt} />
        {reviewCase.priority === "high" && <Badge variant="destructive">{t("highPriority")}</Badge>}
        <span className="text-xs text-muted-foreground">{t(`reasons.${reviewCase.reason}.description`)}</span>
        <Button variant="outline" size="sm" asChild className="ml-auto">
          <Link href={`/fact-checks/${report.id}`} target="_blank">
            <RiFileList3Line aria-hidden /> {t("case.publicReport")}
          </Link>
        </Button>
      </div>

      <div className="grid items-start gap-8 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="flex min-w-0 flex-col gap-8">
          <VerdictSummary report={report} headingLevel={2} className="enter [--d:1]" />
          <CommunityStatusBanner status={score.status} className="enter [--d:2]" />
          <Section id="checked" title={tRep("checked")}>
            <div className="border bg-card p-4">
              <ClaimHighlighter text={report.submittedText} claims={report.claims} citations={report.citations} />
            </div>
          </Section>
          <Section id="findings" title={t("case.aiFindings")}>
            <WhatIsTrueCard whatIsFalse={report.whatIsFalse} whatIsTrue={report.whatIsTrue} />
          </Section>
          {report.aiSignals.length > 0 && (
            <Section id="signals" title={tRep("signals")}>
              <AISignalsList signals={report.aiSignals} />
            </Section>
          )}
          <Section id="sources" title={tRep("sources")}>
            <div className="grid gap-2 md:grid-cols-2">
              {report.citations.map((c, i) => (
                <CitationCard key={c.id} citation={c} index={i + 1} />
              ))}
            </div>
          </Section>
        </div>

        <aside className="flex flex-col gap-4 xl:sticky xl:top-20">
          <DecisionForm report={report} caseId={reviewCase.id} />
          <CommunitySignals report={report} />
          <p className="flex gap-2 text-xs text-muted-foreground">
            <RiShieldUserLine className="size-4 shrink-0" aria-hidden />
            {t("case.auditNote")}
          </p>
        </aside>
      </div>
    </div>
  )
}
