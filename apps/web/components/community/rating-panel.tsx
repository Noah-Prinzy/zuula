"use client"

import * as React from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import {
  RiChat3Line,
  RiThumbDownFill,
  RiThumbDownLine,
  RiThumbUpFill,
  RiThumbUpLine,
} from "@remixicon/react"
import { useTranslations } from "next-intl"
import { toast } from "sonner"

import { CCSMeter } from "@/components/community/ccs-meter"
import { CommunityBadge } from "@/components/community/community-status"
import { useSession } from "@/components/providers/session-provider"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field"
import { Textarea } from "@/components/ui/textarea"
import { fetchFullReport } from "@/lib/fact-checks-api"
import { applyVote, communityScore, RATING_WEIGHTS, raterRole } from "@/lib/community"
import { addComment, rate, ratingsApiConfigured } from "@/lib/ratings-api"
import type { CommunityRating } from "@/lib/types/fact-check"
import { cn } from "@/lib/utils"
import { usePagePath } from "@/hooks/use-page-path"

type Vote = "accurate" | "inaccurate"

const MAX_COMMENT = 280

// FR-RATE-01, 04, 06, 09: one rating per user, changeable, optional reason. Real vote/retract/
// comment calls against the ratings API (lib/ratings-api.ts) when configured; otherwise the
// same local-only optimistic behavior this had before the API existed (demo mode).
export function RatingPanel({
  reportId,
  initial,
  className,
}: {
  reportId: string
  initial: Pick<CommunityRating, "accurate" | "inaccurate" | "myVote">
  className?: string
}) {
  const { user, role } = useSession()
  const router = useRouter()
  const pathname = usePagePath()
  const t = useTranslations("Community.panel")
  const tc = useTranslations("Common")
  const tr = useTranslations("Roles")
  const [counts, setCounts] = React.useState(initial)
  const [vote, setVote] = React.useState<Vote | null>(initial.myVote ?? null)
  const [comment, setComment] = React.useState("")
  const [draft, setDraft] = React.useState("")
  const [dialogOpen, setDialogOpen] = React.useState(false)
  const [busy, setBusy] = React.useState(false)

  // The report page renders server-side with no viewer context (this app's sessions are
  // client-only — see components/providers/session-provider.tsx), so `initial.myVote` is never
  // set there. Once we know who's signed in, re-fetch client-side (credentials ride along
  // automatically) to pick up this viewer's real vote.
  React.useEffect(() => {
    if (!user || !ratingsApiConfigured()) return
    let cancelled = false
    fetchFullReport(reportId)
      .then((r) => {
        if (cancelled || !r) return
        setCounts({ accurate: r.community.accurate, inaccurate: r.community.inaccurate })
        setVote(r.community.myVote ?? null)
      })
      .catch(() => {
        // Keep the SSR snapshot; the next successful vote/retract still reconciles.
      })
    return () => {
      cancelled = true
    }
  }, [user, reportId])

  const score = communityScore(counts)
  const weight = role ? RATING_WEIGHTS[raterRole(role)] : 1

  async function cast(next: Vote) {
    if (!role || next === vote || busy) return
    const previous = { counts, vote }
    setCounts((c) => applyVote(c, raterRole(role), vote, next))
    const changed = vote !== null
    setVote(next)

    if (ratingsApiConfigured()) {
      setBusy(true)
      try {
        await rate(reportId, next)
      } catch {
        setCounts(previous.counts)
        setVote(previous.vote)
        toast.error(t("voteFailed"))
        setBusy(false)
        return
      }
      setBusy(false)
    }

    toast.success(changed ? t("changed") : t("thanks"), {
      description: t("ratedAs", { vote: next }),
      action: { label: t("addReasonAction"), onClick: () => openDialog() },
    })
  }

  function openDialog() {
    setDraft(comment)
    setDialogOpen(true)
  }

  async function saveComment() {
    const text = draft.trim()
    if (ratingsApiConfigured() && vote) {
      setBusy(true)
      try {
        await addComment(reportId, vote, text)
        // Comments are public, SSR-rendered data (components/community/rating-comments.tsx) —
        // a router refresh is enough to show the new one, no separate client fetch needed.
        router.refresh()
      } catch {
        toast.error(t("reasonFailed"))
        setBusy(false)
        return
      }
      setBusy(false)
    }
    setComment(text)
    setDialogOpen(false)
    toast.success(text ? t("reasonSaved") : t("reasonRemoved"))
  }

  return (
    <div className={cn("flex flex-col gap-4 border bg-card p-4", className)}>
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-heading text-sm font-bold">{t("question")}</h3>
        <CommunityBadge status={score.status} />
      </div>

      <div className="grid grid-cols-2 gap-2" role="group" aria-label={t("group")}>
        <Button
          variant="outline"
          size="lg"
          aria-pressed={vote === "accurate"}
          disabled={!user || busy}
          onClick={() => cast("accurate")}
          className={cn(
            vote === "accurate" &&
              "border-verdict-authentic bg-verdict-authentic/10 text-verdict-authentic hover:bg-verdict-authentic/15 hover:text-verdict-authentic"
          )}
        >
          {vote === "accurate" ? <RiThumbUpFill aria-hidden /> : <RiThumbUpLine aria-hidden />}
          {t("accurate")}
        </Button>
        <Button
          variant="outline"
          size="lg"
          aria-pressed={vote === "inaccurate"}
          disabled={!user || busy}
          onClick={() => cast("inaccurate")}
          className={cn(
            vote === "inaccurate" &&
              "border-verdict-false bg-verdict-false/10 text-verdict-false hover:bg-verdict-false/15 hover:text-verdict-false"
          )}
        >
          {vote === "inaccurate" ? <RiThumbDownFill aria-hidden /> : <RiThumbDownLine aria-hidden />}
          {t("inaccurate")}
        </Button>
      </div>

      {!user ? (
        <p className="text-xs text-muted-foreground">
          <Link
            href={`/sign-in?next=${encodeURIComponent(pathname)}`}
            className="font-medium text-primary underline underline-offset-4"
          >
            {t("signIn")}
          </Link>{" "}
          {t("signInRest")}
        </p>
      ) : vote ? (
        <div className="flex flex-col gap-2 text-xs text-muted-foreground">
          <p>
            {t.rich("youRated", {
              vote,
              strong: (chunks) => <span className="font-medium text-foreground">{chunks}</span>,
            })}
          </p>
          {comment && <p className="border-l-2 pl-2 italic">“{comment}”</p>}
          <Button variant="ghost" size="sm" className="w-fit" onClick={openDialog}>
            <RiChat3Line aria-hidden />
            {comment ? t("editReason") : t("addReason")}
          </Button>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          {role ? t("weight", { weight, role: tr(role) }) : t("weightNoRole", { weight })}
        </p>
      )}

      <div className="border-t pt-4">
        <CCSMeter score={score} />
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("dialogTitle", { vote: vote ?? "accurate" })}</DialogTitle>
            <DialogDescription>
              {t("dialogBody")}
            </DialogDescription>
          </DialogHeader>
          <Field>
            <FieldLabel htmlFor="rating-reason">{t("reasonLabel")}</FieldLabel>
            <Textarea
              id="rating-reason"
              value={draft}
              maxLength={MAX_COMMENT}
              onChange={(e) => setDraft(e.target.value)}
              placeholder={t("reasonPlaceholder")}
              rows={4}
            />
            <FieldDescription className="text-right tabular-nums">
              {draft.length}/{MAX_COMMENT}
            </FieldDescription>
          </Field>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline">{tc("cancel")}</Button>
            </DialogClose>
            <Button onClick={saveComment} disabled={busy}>{t("saveReason")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
