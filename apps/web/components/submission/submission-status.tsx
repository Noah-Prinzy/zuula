"use client"

import * as React from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import {
  RiArrowRightLine,
  RiCheckboxCircleFill,
  RiFileCopyLine,
  RiLinkM,
  RiNotification3Line,
  RiRefreshLine,
  RiTimeLine,
} from "@remixicon/react"
import { useTranslations } from "next-intl"
import { toast } from "sonner"

import { useSession } from "@/components/providers/session-provider"
import { startNavigationProgress } from "@/components/shell/route-progress"
import { AnalysisProgress, type AnalysisState } from "@/components/submission/analysis-progress"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { pipelineFor, type StepDef } from "@/lib/analysis"
import { useFormat } from "@/lib/format"
import { getSubmission, type StoredSubmission } from "@/lib/mock/submissions"
import { CONTENT_LANGUAGES } from "@/lib/submission"
import { followSubmission, submissionsLive } from "@/lib/submissions-api"
import { cn } from "@/lib/utils"

const noopSubscribe = () => () => {}
const REDIRECT_SECONDS = 5

// Demo mode: every finished check opens one of the sample reports.
function demoReportFor(s: StoredSubmission | null) {
  return s?.type === "media" ? "/fact-checks/fc-2026-0157" : "/fact-checks/fc-2026-0142"
}

type Progress = {
  state: AnalysisState
  current: number
  elapsed: number
  reportHref: string | null
  /** The API's reason a check failed, when it gave one. */
  error: string | null
  retry: () => void
}

// Elapsed seconds while `running`, picking up where it left off after a retry.
function useElapsed(running: boolean) {
  const [elapsed, setElapsed] = React.useState(0)
  React.useEffect(() => {
    if (!running) return
    const started = Date.now() - elapsed * 1000
    const t = setInterval(() => setElapsed((Date.now() - started) / 1000), 100)
    return () => clearInterval(t)
    // elapsed is read once when the timer (re)starts
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running])
  return elapsed
}

// Live: follow the real pipeline (lib/submissions-api.ts), step by step, to its report.
function useLiveProgress(trackingId: string, steps: StepDef[]): Progress {
  const [current, setCurrent] = React.useState(0)
  const [state, setState] = React.useState<AnalysisState>("running")
  const [reportHref, setReportHref] = React.useState<string | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [attempt, setAttempt] = React.useState(0)
  const elapsed = useElapsed(state === "running")

  React.useEffect(() => {
    return followSubmission(trackingId, {
      onStep: (step) => {
        const index = steps.findIndex((s) => s.id === step.step)
        if (index < 0) return
        const reached = step.status === "done" ? Math.min(index + 1, steps.length - 1) : index
        setCurrent((c) => Math.max(c, reached))
      },
      onFinish: (status) => {
        if (status.status === "completed" && status.result) {
          setCurrent(steps.length - 1)
          setReportHref(`/fact-checks/${status.result.id}`)
          setState("done")
        } else {
          setError(status.error?.error.message ?? null)
          setState("error")
        }
      },
      onError: (e) => {
        setError(e instanceof Error ? e.message : null)
        setState("error")
      },
    })
  }, [trackingId, steps, attempt])

  return {
    state,
    current,
    elapsed,
    reportHref,
    error,
    retry: () => {
      setError(null)
      setState("running")
      setAttempt((a) => a + 1)
    },
  }
}

// Demo mode (no API): step through the pipeline on its expected timings.
function useDemoProgress(submission: StoredSubmission | null, steps: StepDef[]): Progress {
  // No local record means the submission was made elsewhere: treat it as already finished.
  const [current, setCurrent] = React.useState(0)
  const [state, setState] = React.useState<AnalysisState>(submission ? "running" : "done")
  const [attempt, setAttempt] = React.useState(0)
  const elapsed = useElapsed(state === "running")

  // Demo of the failure path: links containing "fail" can't be fetched on the first attempt.
  const failsAt =
    attempt === 0 && submission?.type === "url" && submission.preview.includes("fail")
      ? steps.findIndex((s) => s.id === "fetch")
      : -1

  React.useEffect(() => {
    if (state !== "running") return
    const t = setTimeout(() => {
      if (current === failsAt) setState("error")
      else if (current + 1 >= steps.length) setState("done")
      else setCurrent((c) => c + 1)
    }, steps[current].seconds * 1000)
    return () => clearTimeout(t)
  }, [state, current, steps, failsAt])

  return {
    state,
    current,
    elapsed,
    reportHref: demoReportFor(submission),
    error: null,
    retry: () => {
      setAttempt((a) => a + 1)
      setState("running")
    },
  }
}

async function copy(text: string, success: string, failure: string) {
  try {
    await navigator.clipboard.writeText(text)
    toast.success(success)
  } catch {
    toast.error(failure)
  }
}

function TrackingIdCard({ trackingId }: { trackingId: string }) {
  const t = useTranslations("Status")
  return (
    <div className="flex flex-col gap-3 border bg-card p-4">
      <div>
        <p className="text-xs text-muted-foreground">{t("trackingId")}</p>
        <p className="font-mono text-2xl font-bold tracking-wider">{trackingId}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={() => copy(trackingId, t("idCopied"), t("copyFailed"))}>
          <RiFileCopyLine aria-hidden /> {t("copyId")}
        </Button>
        <Button variant="outline" size="sm" onClick={() => copy(window.location.href, t("linkCopied"), t("copyFailed"))}>
          <RiLinkM aria-hidden /> {t("copyLink")}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">{t("saveIdHint")}</p>
    </div>
  )
}

function Tracker({
  trackingId,
  submission,
  steps,
  progress,
}: {
  trackingId: string
  submission: StoredSubmission | null
  steps: StepDef[]
  progress: Progress
}) {
  const t = useTranslations("Status")
  const ts = useTranslations("Submit")
  const f = useFormat()
  const router = useRouter()
  const { source } = useSession()
  const signedIn = source === "account"
  const type = submission?.type ?? "text"
  const { state, current, elapsed, reportHref, error, retry } = progress

  // FR-SUBMIT-06: open the report automatically when a check you just submitted finishes.
  const [countdown, setCountdown] = React.useState<number | null>(submission ? REDIRECT_SECONDS : null)
  React.useEffect(() => {
    if (state !== "done" || countdown === null || !reportHref) return
    if (countdown === 0) {
      startNavigationProgress()
      router.push(reportHref)
      return
    }
    const t = setTimeout(() => setCountdown((c) => (c === null ? null : c - 1)), 1000)
    return () => clearTimeout(t)
  }, [state, countdown, router, reportHref])

  const language =
    CONTENT_LANGUAGES.find((l) => l.code === submission?.language)?.label ?? ts("detectLanguage")

  return (
    <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_22rem] xl:grid-cols-[minmax(0,1fr)_26rem]">
      <div className="flex flex-col gap-6">
        {state === "done" ? (
          <div className="flex flex-col gap-4 border border-verdict-authentic/40 bg-verdict-authentic/5 p-5">
            <div className="flex items-start gap-3">
              <RiCheckboxCircleFill className="size-7 shrink-0 text-verdict-authentic" aria-hidden />
              <div>
                <h2 className="font-heading text-lg font-bold">{t("readyTitle")}</h2>
                <p className="text-sm text-muted-foreground">
                  {countdown !== null ? t("openingIn", { count: countdown }) : t("readyBody")}
                </p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button asChild size="lg">
                <Link href={reportHref ?? "/fact-checks"}>
                  {t("viewReport")} <RiArrowRightLine aria-hidden />
                </Link>
              </Button>
              {countdown !== null && (
                <Button variant="ghost" size="lg" onClick={() => setCountdown(null)}>
                  {t("stay")}
                </Button>
              )}
            </div>
          </div>
        ) : state === "error" ? (
          <div role="alert" className="flex flex-col gap-3 border border-destructive/40 bg-destructive/5 p-5">
            <h2 className="font-heading text-lg font-bold">{t("errorTitle")}</h2>
            <p className="text-sm text-muted-foreground">{error ?? t("errorBody")}</p>
            <div className="flex flex-wrap gap-2">
              <Button onClick={retry}>
                <RiRefreshLine aria-hidden /> {t("tryAgain")}
              </Button>
              <Button variant="outline" asChild>
                <Link href="/verify">{t("pasteInstead")}</Link>
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <RiTimeLine className="size-4" aria-hidden />
            <span>
              {t("elapsed", {
                seconds: f.number(elapsed, { minimumFractionDigits: 1, maximumFractionDigits: 1 }),
                expected: t(type === "media" ? "expected.media" : "expected.text"),
              })}
            </span>
          </div>
        )}

        <section aria-labelledby="progress-title" className="border bg-card p-5">
          <h2 id="progress-title" className="sr-only">
            {t("progressTitle")}
          </h2>
          <AnalysisProgress
            steps={steps}
            current={current}
            state={state}
            error={t("fetchError")}
          />
        </section>

        {submission && (
          <section aria-labelledby="submitted-title" className="border bg-card p-5">
            <h2 id="submitted-title" className="mb-2 font-heading text-sm font-bold">
              {t("submittedTitle")}
            </h2>
            <p className={cn("text-sm break-words", submission.type === "url" && "font-mono")}>
              {submission.preview || "—"}
            </p>
            <p className="mt-2 text-xs text-muted-foreground">
              {t("submittedMeta", {
                type: t(`types.${submission.type}`),
                language,
                time: f.date(submission.submittedAt, "time"),
              })}
            </p>
          </section>
        )}
      </div>

      <aside className="flex flex-col gap-6">
        <TrackingIdCard trackingId={trackingId} />
        <div className="flex gap-3 border bg-card p-4 text-sm">
          <RiNotification3Line className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
          {signedIn ? (
            <p>{t("notifySignedIn")}</p>
          ) : (
            <p>
              {t.rich("notifyGuest", {
                link: (chunks) => (
                  <Link href="/sign-up" className="font-medium text-primary underline underline-offset-4">
                    {chunks}
                  </Link>
                ),
              })}
            </p>
          )}
        </div>
      </aside>
    </div>
  )
}

function LiveTracker({ trackingId, submission }: { trackingId: string; submission: StoredSubmission | null }) {
  const steps = React.useMemo(() => pipelineFor(submission?.type ?? "text"), [submission?.type])
  const progress = useLiveProgress(trackingId, steps)
  return <Tracker trackingId={trackingId} submission={submission} steps={steps} progress={progress} />
}

function DemoTracker({ trackingId, submission }: { trackingId: string; submission: StoredSubmission | null }) {
  const steps = React.useMemo(() => pipelineFor(submission?.type ?? "text"), [submission?.type])
  const progress = useDemoProgress(submission, steps)
  return <Tracker trackingId={trackingId} submission={submission} steps={steps} progress={progress} />
}

export function SubmissionStatus({ trackingId }: { trackingId: string }) {
  // sessionStorage is only readable in the browser; render a skeleton until then.
  const mounted = React.useSyncExternalStore(noopSubscribe, () => true, () => false)
  const submission = React.useMemo(
    () => (mounted ? getSubmission(trackingId) : null),
    [mounted, trackingId]
  )

  if (!mounted) return <Skeleton className="h-96 w-full" />
  const Driver = submissionsLive() ? LiveTracker : DemoTracker
  return <Driver key={trackingId} trackingId={trackingId} submission={submission} />
}
