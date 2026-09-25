import {
  RiAlertLine,
  RiGroupLine,
  RiPauseCircleLine,
  RiShieldStarLine,
  type RemixiconComponentType,
} from "@remixicon/react"
import { useTranslations } from "next-intl"

import type { CommunityStatus } from "@/lib/community"
import { cn } from "@/lib/utils"

// Text lives in Community.status.<status>.{label,title,description}.
type StatusMeta = {
  icon: RemixiconComponentType
  className: string
}

// §9.2 escalation states. "standard" (CCS 70–89 or too few ratings) shows nothing.
export const COMMUNITY_STATUS_META: Record<Exclude<CommunityStatus, "standard">, StatusMeta> = {
  verified: {
    icon: RiShieldStarLine,
    className: "border-verdict-authentic/40 bg-verdict-authentic/10 text-verdict-authentic",
  },
  questioned: {
    icon: RiGroupLine,
    className: "border-verdict-likely-false/40 bg-verdict-likely-false/10 text-verdict-likely-false",
  },
  escalated: {
    icon: RiAlertLine,
    className: "border-verdict-false/40 bg-verdict-false/10 text-verdict-false",
  },
  suspended: {
    icon: RiPauseCircleLine,
    className: "border-verdict-false/60 bg-verdict-false/15 text-verdict-false",
  },
}

// Compact badge for cards and lists.
export function CommunityBadge({
  status,
  className,
}: {
  status: CommunityStatus
  className?: string
}) {
  const t = useTranslations("Community.status")
  if (status === "standard") return null
  const meta = COMMUNITY_STATUS_META[status]
  return (
    <span
      className={cn(
        "inline-flex min-h-5 w-fit max-w-full items-center gap-1 border px-1.5 text-xs font-medium",
        meta.className,
        className
      )}
    >
      <meta.icon className="size-3" aria-hidden />
      {t(`${status}.label`)}
    </span>
  )
}

// Full-width banner at the top of a report.
export function CommunityStatusBanner({
  status,
  className,
}: {
  status: CommunityStatus
  className?: string
}) {
  const t = useTranslations("Community.status")
  if (status === "standard") return null
  const meta = COMMUNITY_STATUS_META[status]
  return (
    <div
      role={status === "verified" ? "status" : "alert"}
      className={cn("flex items-start gap-3 border p-3", meta.className, className)}
    >
      <meta.icon className="mt-0.5 size-5 shrink-0" aria-hidden />
      <div className="flex flex-col gap-0.5">
        <p className="font-heading text-sm font-bold">{t(`${status}.title`)}</p>
        <p className="text-sm text-foreground/80">{t(`${status}.description`)}</p>
      </div>
    </div>
  )
}
