"use client"

import * as React from "react"
import { RiExternalLinkLine, RiFileTextLine } from "@remixicon/react"
import { useTranslations } from "next-intl"
import { toast } from "sonner"

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
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { useApiErrorMessage } from "@/hooks/use-api-error-message"
import { useFormat } from "@/lib/format"
import { SAMPLE_APPLICATIONS } from "@/lib/mock/admin"
import { cn, initials } from "@/lib/utils"
import {
  decideApplication,
  documentExpired,
  documentHref,
  getApplication,
  listApplications,
  verificationApiConfigured,
  type AccreditationApplication,
  type AccreditationApplicationDetail,
  type AccreditationStatus,
} from "@/lib/verification-api"

const PER_PAGE = 20
const MIN_NOTE = 5 // matches the API: a rejection needs a reason the applicant can read

const STATUS_STYLE: Record<AccreditationStatus, string> = {
  pending: "border-verdict-likely-false/40 bg-verdict-likely-false/10 text-verdict-likely-false",
  approved: "border-verdict-authentic/40 bg-verdict-authentic/10 text-verdict-authentic",
  rejected: "border-verdict-false/40 bg-verdict-false/10 text-verdict-false",
}

function StatusBadge({ status }: { status: AccreditationStatus }) {
  const t = useTranslations("Admin.verifications.statuses")
  return (
    <span className={cn("inline-flex min-h-5 items-center border px-1.5 text-xs", STATUS_STYLE[status])}>
      {t(status)}
    </span>
  )
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm break-words">{children}</dd>
    </div>
  )
}

// FR-AUTH-02: the accreditation queue. Approving gives the applicant the role they applied for
// (Verified Journalist or Expert Reviewer); rejecting needs a note they'll see. Without an API
// (the demo), the sample applications are decided locally.
export function VerificationReview() {
  const live = verificationApiConfigured()
  const [status, setStatus] = React.useState<AccreditationStatus | "">("pending")
  const [page, setPage] = React.useState(1)
  const [loaded, setLoaded] = React.useState<{ key: string; items: AccreditationApplication[]; total: number } | null>(null)
  const [demo, setDemo] = React.useState(SAMPLE_APPLICATIONS)
  const [openId, setOpenId] = React.useState<string | null>(null)
  const [reload, setReload] = React.useState(0)
  const t = useTranslations("Admin.verifications")
  const tRoles = useTranslations("Roles")
  const f = useFormat()
  const errorMessage = useApiErrorMessage()

  // Which page of the queue is on screen; a result for an older key means "still loading".
  const key = `${status}|${page}|${reload}`
  React.useEffect(() => {
    if (!live) return
    let cancelled = false
    listApplications({ status: status || undefined, page, perPage: PER_PAGE })
      .then((r) => !cancelled && setLoaded({ key, items: r.data, total: r.total }))
      .catch((e) => {
        if (cancelled) return
        setLoaded({ key, items: [], total: 0 })
        toast.error(t("loadFailed"), { description: errorMessage(e) })
      })
    return () => {
      cancelled = true
    }
  }, [live, key, status, page, t, errorMessage])

  const demoItems = React.useMemo(() => demo.filter((a) => !status || a.status === status), [demo, status])
  const items = live ? (loaded?.key === key ? loaded.items : null) : demoItems
  const total = live ? (loaded?.total ?? 0) : demoItems.length

  const pages = Math.max(1, Math.ceil(total / PER_PAGE))

  function decided(app: AccreditationApplicationDetail) {
    if (live) setReload((n) => n + 1)
    else setDemo((xs) => xs.map((x) => (x.id === app.id ? app : x)))
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <p className="text-sm text-muted-foreground" aria-live="polite">
          {items === null ? t("loading") : t("summary", { count: total })}
        </p>
        <label htmlFor="verifications-status" className="sr-only">
          {t("status")}
        </label>
        <NativeSelect
          id="verifications-status"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value as AccreditationStatus | "")
            setPage(1)
          }}
        >
          <NativeSelectOption value="pending">{t("statuses.pending")}</NativeSelectOption>
          <NativeSelectOption value="approved">{t("statuses.approved")}</NativeSelectOption>
          <NativeSelectOption value="rejected">{t("statuses.rejected")}</NativeSelectOption>
          <NativeSelectOption value="">{t("allStatuses")}</NativeSelectOption>
        </NativeSelect>
      </div>

      {items === null ? (
        <div className="flex flex-col gap-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyTitle>{status === "pending" ? t("emptyPendingTitle") : t("emptyTitle")}</EmptyTitle>
            <EmptyDescription>{t("emptyBody")}</EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <ul className="flex flex-col divide-y border bg-card">
          {items.map((a) => (
            <li key={a.id} className="flex flex-col gap-3 p-4 md:flex-row md:items-center">
              <div className="flex min-w-0 flex-1 items-start gap-3">
                <Avatar className="size-9">
                  <AvatarFallback>{initials(a.applicant.name)}</AvatarFallback>
                </Avatar>
                <div className="flex min-w-0 flex-col gap-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{a.applicant.name}</span>
                    <StatusBadge status={a.status} />
                  </div>
                  <span className="truncate text-xs text-muted-foreground">{a.applicant.email}</span>
                  <span className="text-sm">
                    {t("appliedFor", { role: tRoles(a.requestedRole) })}
                    {a.organisation ? ` · ${a.organisation}` : ""}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {t("submitted", { date: f.dateTime(a.submittedAt) })}
                  </span>
                </div>
              </div>
              <Button variant={a.status === "pending" ? "default" : "outline"} size="sm" onClick={() => setOpenId(a.id)}>
                {a.status === "pending" ? t("review") : t("view")}
              </Button>
            </li>
          ))}
        </ul>
      )}

      {live && pages > 1 && (
        <div className="flex items-center justify-end gap-2">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            {t("previous")}
          </Button>
          <span className="text-sm text-muted-foreground">{t("page", { page, pages })}</span>
          <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
            {t("next")}
          </Button>
        </div>
      )}

      <ApplicationSheet
        key={openId ?? "closed"}
        id={openId}
        live={live}
        demoApplication={demo.find((a) => a.id === openId) ?? null}
        onClose={() => setOpenId(null)}
        onDecided={decided}
      />
    </div>
  )
}

function ApplicationSheet({
  id,
  live,
  demoApplication,
  onClose,
  onDecided,
}: {
  id: string | null
  live: boolean
  demoApplication: AccreditationApplicationDetail | null
  onClose: () => void
  onDecided: (app: AccreditationApplicationDetail) => void
}) {
  const [fetched, setFetched] = React.useState<AccreditationApplicationDetail | null>(null)
  const [confirming, setConfirming] = React.useState(false)
  const [rejecting, setRejecting] = React.useState(false)
  const [note, setNote] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const t = useTranslations("Admin.verifications")
  const tRoles = useTranslations("Roles")
  const tc = useTranslations("Common")
  const ta = useTranslations("Admin")
  const tStatus = useTranslations("Admin.users.statuses")
  const f = useFormat()
  const errorMessage = useApiErrorMessage()

  const load = React.useCallback(
    (appId: string) =>
      getApplication(appId)
        .then(setFetched)
        .catch((e) => toast.error(t("loadFailed"), { description: errorMessage(e) })),
    [t, errorMessage]
  )

  // The parent remounts this per application (key={id}), so the reject form starts fresh.
  React.useEffect(() => {
    if (id && live) load(id)
  }, [id, live, load])

  const app = live ? (fetched?.id === id ? fetched : null) : demoApplication

  async function decide(decision: "approve" | "reject") {
    if (!app) return
    const name = app.applicant.name
    const role = tRoles(app.requestedRole)
    setBusy(true)
    try {
      const result = live
        ? await decideApplication(app.id, decision === "reject" ? { decision, note: note.trim() } : { decision })
        : demoDecision(app, decision, note.trim())
      setFetched(result)
      onDecided(result)
      toast.success(decision === "approve" ? t("approvedToast", { name, role }) : t("rejectedToast", { name }), {
        description: ta("loggedInAudit"),
      })
      setRejecting(false)
      setNote("")
    } catch (e) {
      toast.error(t("decisionFailed"), { description: errorMessage(e) })
    } finally {
      setBusy(false)
      setConfirming(false)
    }
  }

  return (
    <Sheet open={id !== null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full gap-0 overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{app ? app.applicant.name : t("loading")}</SheetTitle>
          <SheetDescription>
            {app ? t("appliedFor", { role: tRoles(app.requestedRole) }) : t("detailDescription")}
          </SheetDescription>
        </SheetHeader>

        {!app ? (
          <div className="flex flex-col gap-3 p-4">
            <Skeleton className="h-24" />
            <Skeleton className="h-16" />
          </div>
        ) : (
          <div className="flex flex-col gap-6 p-4">
            <section className="flex flex-col gap-3">
              <h3 className="text-sm font-medium">{t("applicant")}</h3>
              <dl className="grid grid-cols-2 gap-3">
                <Fact label={t("fields.email")}>{app.applicant.email}</Fact>
                <Fact label={t("fields.currentRole")}>{tRoles(app.applicant.role)}</Fact>
                <Fact label={t("fields.accountStatus")}>{tStatus(app.applicant.status)}</Fact>
                <Fact label={t("fields.joined")}>{f.date(app.applicant.joined)}</Fact>
                {app.applicant.district && <Fact label={t("fields.district")}>{app.applicant.district}</Fact>}
              </dl>
            </section>

            <section className="flex flex-col gap-3">
              <h3 className="text-sm font-medium">{t("application")}</h3>
              <dl className="grid grid-cols-2 gap-3">
                <Fact label={t("fields.status")}>
                  <StatusBadge status={app.status} />
                </Fact>
                <Fact label={t("fields.requestedRole")}>
                  <Badge variant="outline">{tRoles(app.requestedRole)}</Badge>
                </Fact>
                <Fact label={t("fields.organisation")}>{app.organisation || t("none")}</Fact>
                <Fact label={t("fields.pressCard")}>{app.pressCardNumber || t("none")}</Fact>
                <Fact label={t("fields.submittedAt")}>{f.dateTime(app.submittedAt)}</Fact>
                {app.reviewedAt && (
                  <Fact label={t("fields.decided")}>
                    {app.reviewer
                      ? t("decidedBy", { date: f.dateTime(app.reviewedAt), name: app.reviewer })
                      : f.dateTime(app.reviewedAt)}
                  </Fact>
                )}
              </dl>
              {app.note && (
                <Fact label={t("fields.note")}>
                  <span className="border-l-2 pl-2 text-muted-foreground italic">{app.note}</span>
                </Fact>
              )}
            </section>

            <section className="flex flex-col gap-3">
              <h3 className="text-sm font-medium">{t("documents", { count: app.documentCount })}</h3>
              {app.documents.length === 0 ? (
                <p className="text-sm text-muted-foreground">{live ? t("noDocuments") : t("demoDocuments")}</p>
              ) : (
                <ul className="flex flex-col gap-2">
                  {app.documents.map((d) =>
                    documentExpired(d) ? (
                      <li key={d.index} className="flex items-center justify-between gap-2 border p-2 text-sm">
                        <span className="text-muted-foreground">{t("linkExpired")}</span>
                        <Button variant="ghost" size="sm" onClick={() => load(app.id)}>
                          {t("refreshLinks")}
                        </Button>
                      </li>
                    ) : (
                      <li key={d.index}>
                        <a
                          href={documentHref(d)}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex items-center gap-2 border p-2 text-sm hover:border-primary hover:text-primary"
                        >
                          <RiFileTextLine className="size-4 shrink-0" aria-hidden />
                          <span className="flex-1">{t("document", { number: d.index + 1 })}</span>
                          <RiExternalLinkLine className="size-4 shrink-0" aria-hidden />
                          <span className="sr-only">{t("opensInNewTab")}</span>
                        </a>
                      </li>
                    )
                  )}
                </ul>
              )}
              <p className="text-xs text-muted-foreground">{t("scanned")}</p>
            </section>

            {app.status === "pending" && rejecting && (
              <section className="flex flex-col gap-2">
                <label htmlFor="verification-note" className="text-sm font-medium">
                  {t("rejectReason")}
                </label>
                <Textarea
                  id="verification-note"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder={t("rejectPlaceholder")}
                  rows={3}
                />
              </section>
            )}
          </div>
        )}

        {app?.status === "pending" && (
          <SheetFooter className="flex-row flex-wrap justify-end gap-2 border-t">
            {rejecting ? (
              <>
                <Button variant="ghost" onClick={() => setRejecting(false)} disabled={busy}>
                  {tc("cancel")}
                </Button>
                <Button
                  variant="destructive"
                  disabled={busy || note.trim().length < MIN_NOTE}
                  onClick={() => decide("reject")}
                >
                  {t("confirmReject")}
                </Button>
              </>
            ) : (
              <>
                <Button variant="outline" onClick={() => setRejecting(true)} disabled={busy}>
                  {t("reject")}
                </Button>
                <Button onClick={() => setConfirming(true)} disabled={busy}>
                  {t("approve")}
                </Button>
              </>
            )}
          </SheetFooter>
        )}

        <AlertDialog open={confirming} onOpenChange={setConfirming}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>
                {app ? t("approveTitle", { name: app.applicant.name, role: tRoles(app.requestedRole) }) : ""}
              </AlertDialogTitle>
              <AlertDialogDescription>
                {app?.requestedRole === "expert" ? t("approveExpertBody") : t("approveBody")}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel disabled={busy}>{tc("cancel")}</AlertDialogCancel>
              <AlertDialogAction disabled={busy} onClick={() => decide("approve")}>
                {t("approve")}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </SheetContent>
    </Sheet>
  )
}

// The demo's stand-in for POST /admin/verifications/{id}/decision.
function demoDecision(
  app: AccreditationApplicationDetail,
  decision: "approve" | "reject",
  note: string
): AccreditationApplicationDetail {
  const applicant = {
    ...app.applicant,
    role: decision === "approve" ? app.requestedRole : app.applicant.role,
    status: app.applicant.status === "pending" ? ("active" as const) : app.applicant.status,
  }
  return {
    ...app,
    status: decision === "approve" ? "approved" : "rejected",
    reviewedAt: new Date().toISOString(),
    reviewer: "Mary Akello",
    note: note || undefined,
    applicant,
  }
}
