import {
  RiAlarmWarningLine,
  RiFlagLine,
  RiGroupLine,
  RiPauseCircleLine,
  RiQuestionLine,
  RiTimeLine,
} from "@remixicon/react"
import { useTranslations } from "next-intl"

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useFormat } from "@/lib/format"
import { slaFor, type ReviewReason } from "@/lib/mock/review"
import { cn } from "@/lib/utils"

// Labels live in Review.sla.<state>.
const SLA_STYLE = {
  overdue: { className: "border-verdict-false/40 bg-verdict-false/10 text-verdict-false", icon: RiAlarmWarningLine },
  "due-soon": { className: "border-verdict-likely-false/40 bg-verdict-likely-false/10 text-verdict-likely-false", icon: RiTimeLine },
  "on-track": { className: "text-muted-foreground", icon: RiTimeLine },
}

/** "3 h 20 min left" / "45 min overdue" */
export function useSlaText() {
  const t = useTranslations("Review.sla")
  return (hoursLeft: number) => {
    const abs = Math.abs(hoursLeft)
    const time =
      abs < 1
        ? t("minutes", { minutes: Math.round(abs * 60) })
        : t("hoursMinutes", { hours: Math.floor(abs), minutes: Math.round((abs % 1) * 60) })
    return hoursLeft < 0 ? t("late", { time }) : t("left", { time })
  }
}

// FR-REVIEW-06: time left on the 48-hour review SLA.
export function SlaBadge({ flaggedAt, className }: { flaggedAt: string; className?: string }) {
  const t = useTranslations("Review.sla")
  const slaText = useSlaText()
  const f = useFormat()
  const sla = slaFor(flaggedAt)
  const s = SLA_STYLE[sla.state]
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          tabIndex={0}
          className={cn("inline-flex min-h-5 w-fit max-w-full items-center gap-1 border px-1.5 text-xs tabular-nums", s.className, className)}
        >
          <s.icon className="size-3" aria-hidden />
          {slaText(sla.hoursLeft)}
        </span>
      </TooltipTrigger>
      <TooltipContent>
        {t("tooltip", {
          status: t(sla.state),
          time: f.date(sla.due, { weekday: "short", hour: "2-digit", minute: "2-digit" }),
        })}
      </TooltipContent>
    </Tooltip>
  )
}

const REASON_ICON: Record<ReviewReason, typeof RiFlagLine> = {
  "community-escalation": RiGroupLine,
  suspended: RiPauseCircleLine,
  "user-reports": RiFlagLine,
  "low-confidence": RiQuestionLine,
}

export function ReasonBadge({ reason, reports, className }: { reason: ReviewReason; reports?: number; className?: string }) {
  const t = useTranslations("Review.reasons")
  const Icon = REASON_ICON[reason]
  return (
    <span className={cn("inline-flex items-center gap-1 text-xs whitespace-nowrap text-muted-foreground", className)}>
      <Icon className="size-3.5" aria-hidden />
      {t(`${reason}.label`)}
      {reports ? ` (${reports})` : ""}
    </span>
  )
}

export function StatCard({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string
  value: string | number
  hint?: string
  tone?: "default" | "danger" | "warning" | "good"
}) {
  return (
    <div className="hover-lift flex flex-col gap-1 border bg-card p-4">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span
        className={cn(
          "font-heading text-3xl font-bold tabular-nums",
          tone === "danger" && "text-verdict-false",
          tone === "warning" && "text-verdict-likely-false",
          tone === "good" && "text-verdict-authentic"
        )}
      >
        {value}
      </span>
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
    </div>
  )
}
