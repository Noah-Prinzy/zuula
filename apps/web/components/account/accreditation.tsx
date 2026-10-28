"use client"

import * as React from "react"
import {
  RiAwardFill,
  RiCheckLine,
  RiFileUploadLine,
  RiScales3Line,
  RiTimeLine,
  RiVerifiedBadgeLine,
} from "@remixicon/react"
import { useTranslations } from "next-intl"
import { toast } from "sonner"

import { SettingsSection } from "@/components/account/settings-section"
import { useSession } from "@/components/providers/session-provider"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Skeleton } from "@/components/ui/skeleton"
import { useApiErrorMessage } from "@/hooks/use-api-error-message"
import { useLiveData } from "@/hooks/use-live-data"
import { accountApi, accountApiLive, type Verification } from "@/lib/account-api"
import { identifierKind } from "@/lib/auth"
import { useFormat } from "@/lib/format"
import { formatBytes, MAX_FILE_BYTES } from "@/lib/submission"
import { cn } from "@/lib/utils"

// Text lives in Account.accreditation.benefits.<key>.
const BENEFITS = [
  { key: "weight", icon: RiScales3Line },
  { key: "badge", icon: RiVerifiedBadgeLine },
  { key: "api", icon: RiAwardFill },
] as const

const OUTLETS = ["New Vision", "Daily Monitor", "Nile Post", "ChimpReports", "Uganda Radio Network", "The Observer", "NBS Television", "NTV Uganda"]

type Stage = "form" | "submitted"

function Benefits() {
  const t = useTranslations("Account.accreditation.benefits")
  return (
    <ul className="flex flex-col gap-3">
      {BENEFITS.map((b) => (
        <li key={b.key} className="flex gap-3 text-sm">
          <b.icon className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
          {t(b.key)}
        </li>
      ))}
    </ul>
  )
}

function Timeline({ submittedAt }: { submittedAt: Date }) {
  const t = useTranslations("Account.accreditation.timeline")
  const f = useFormat()
  const steps: { label: string; detail: string; done?: boolean; active?: boolean }[] = [
    { label: t("submitted"), detail: f.dateTime(submittedAt), done: true },
    { label: t("review"), detail: t("reviewDetail"), active: true },
    { label: t("decision"), detail: t("decisionDetail") },
  ]
  return (
    <ol className="flex flex-col">
      {steps.map((s, i) => (
        <li key={s.label} className="relative flex gap-3 pb-5 last:pb-0">
          {i < steps.length - 1 && <span className="absolute top-6 bottom-0 left-2.75 w-px bg-border" aria-hidden />}
          <span
            className={cn(
              "relative z-10 flex size-6 shrink-0 items-center justify-center border bg-background",
              s.done && "border-verdict-authentic bg-verdict-authentic text-background",
              s.active && "border-primary text-primary"
            )}
            aria-hidden
          >
            {s.done ? <RiCheckLine className="size-3.5" /> : s.active ? <RiTimeLine className="size-3.5" /> : null}
          </span>
          <div className="flex flex-col">
            <span className={cn("text-sm", s.done || s.active ? "font-medium" : "text-muted-foreground")}>{s.label}</span>
            <span className="text-xs text-muted-foreground">{s.detail}</span>
          </div>
        </li>
      ))}
    </ol>
  )
}

function ApplicationForm({ onSubmitted }: { onSubmitted: () => void }) {
  const { user } = useSession()
  const [outlet, setOutlet] = React.useState("")
  const [title, setTitle] = React.useState("")
  const [workEmail, setWorkEmail] = React.useState("")
  const [membership, setMembership] = React.useState("")
  const [links, setLinks] = React.useState("")
  const [file, setFile] = React.useState<File | null>(null)
  const [declare, setDeclare] = React.useState(false)
  const [errors, setErrors] = React.useState<Record<string, string>>({})
  const [busy, setBusy] = React.useState(false)
  const t = useTranslations("Account.accreditation")

  const errorMessage = useApiErrorMessage()

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    const next: Record<string, string> = {}
    if (outlet.trim().length < 2) next.outlet = t("errors.outlet")
    if (title.trim().length < 2) next.title = t("errors.title")
    if (identifierKind(workEmail) !== "email") next.workEmail = t("errors.workEmail")
    if (!file) next.file = t("errors.file")
    else if (file.size > MAX_FILE_BYTES) next.file = t("errors.fileSize")
    if (!declare) next.declare = t("errors.declare")
    setErrors(next)
    if (Object.keys(next).length) return
    setBusy(true)
    if (accountApiLive()) {
      // POST /me/verification takes the outlet, the document and an optional press-card number;
      // job title, work email and links have no API field yet and aren't sent.
      const form = new FormData()
      form.append("organisation", outlet.trim())
      form.append("role", "journalist")
      if (membership.trim()) form.append("pressCardNumber", membership.trim())
      form.append("documents", file!)
      try {
        await accountApi.applyForVerification(form)
      } catch (err) {
        setBusy(false)
        toast.error(errorMessage(err))
        return
      }
    } else {
      await new Promise((r) => setTimeout(r, 700))
    }
    setBusy(false)
    onSubmitted()
    toast.success(t("submitted"), { description: t("submittedBody") })
  }

  return (
    <form noValidate onSubmit={submit} className="contents">
      <SettingsSection
        id="apply"
        title={t("applyTitle")}
        description={t("applyDescription", { name: user?.name ?? t("you") })}
        footer={
          <Button type="submit" disabled={busy}>
            {busy ? t("submitting") : t("submit")}
          </Button>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Field data-invalid={!!errors.outlet}>
            <FieldLabel htmlFor="acc-outlet">{t("outlet")}</FieldLabel>
            <Input id="acc-outlet" list="acc-outlets" value={outlet} onChange={(e) => setOutlet(e.target.value)} aria-invalid={!!errors.outlet} />
            <datalist id="acc-outlets">
              {OUTLETS.map((o) => (
                <option key={o} value={o} />
              ))}
            </datalist>
            {errors.outlet && <FieldError>{errors.outlet}</FieldError>}
          </Field>
          <Field data-invalid={!!errors.title}>
            <FieldLabel htmlFor="acc-title">{t("jobTitle")}</FieldLabel>
            <Input id="acc-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t("jobTitlePlaceholder")} aria-invalid={!!errors.title} />
            {errors.title && <FieldError>{errors.title}</FieldError>}
          </Field>
          <Field data-invalid={!!errors.workEmail}>
            <FieldLabel htmlFor="acc-email">{t("workEmail")}</FieldLabel>
            <Input id="acc-email" type="email" value={workEmail} onChange={(e) => setWorkEmail(e.target.value)} placeholder="name@newsroom.co.ug" aria-invalid={!!errors.workEmail} />
            <FieldDescription>{t("workEmailHint")}</FieldDescription>
            {errors.workEmail && <FieldError>{errors.workEmail}</FieldError>}
          </Field>
          <Field>
            <FieldLabel htmlFor="acc-membership">{t("membership")}</FieldLabel>
            <Input id="acc-membership" value={membership} onChange={(e) => setMembership(e.target.value)} placeholder={t("membershipPlaceholder")} />
          </Field>
          <Field data-invalid={!!errors.file} className="sm:col-span-2">
            <FieldLabel htmlFor="acc-file">{t("file")}</FieldLabel>
            <label
              htmlFor="acc-file"
              className={cn(
                "flex cursor-pointer items-center gap-3 border border-dashed p-3 text-sm hover:bg-muted/40 focus-within:ring-2 focus-within:ring-ring",
                errors.file && "border-destructive"
              )}
            >
              <RiFileUploadLine className="size-5 text-muted-foreground" aria-hidden />
              <span className="min-w-0 flex-1 truncate">
                {file ? `${file.name} · ${formatBytes(file.size)}` : t("filePrompt")}
              </span>
              <input
                id="acc-file"
                type="file"
                accept="application/pdf,image/jpeg,image/png"
                className="sr-only"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </label>
            {errors.file && <FieldError>{errors.file}</FieldError>}
          </Field>
          <Field className="sm:col-span-2">
            <FieldLabel htmlFor="acc-links">{t("links")}</FieldLabel>
            <Textarea id="acc-links" rows={3} value={links} onChange={(e) => setLinks(e.target.value)} placeholder={t("linksPlaceholder")} />
          </Field>
          <Field data-invalid={!!errors.declare} className="sm:col-span-2">
            <div className="flex items-start gap-2">
              <Checkbox id="acc-declare" checked={declare} onCheckedChange={(c) => setDeclare(c === true)} className="mt-0.5" aria-invalid={!!errors.declare} />
              <FieldLabel htmlFor="acc-declare" className="block font-normal leading-snug">
                {t("declaration")}
              </FieldLabel>
            </div>
            {errors.declare && <FieldError>{errors.declare}</FieldError>}
          </Field>
        </div>
      </SettingsSection>
    </form>
  )
}

// FR-AUTH-02 / FR-RATE-06: becoming a Verified Journalist.
// FR-AUTH-02: Verified Journalist accreditation. Live, the application and its status are the
// API's (POST/GET /me/verification) and an admin decides it in Admin → Verifications; demo
// builds simulate both. The API has no withdrawal, so that button is demo-only.
export function Accreditation() {
  const live = accountApiLive()
  const { data } = useLiveData<Verification>(live, accountApi.verification, { status: "none" }, [])
  if (!data) return <Skeleton className="h-96 w-full" />
  return <AccreditationView live={live} status={data} />
}

function AccreditationView({ live, status }: { live: boolean; status: Verification }) {
  const { role, user } = useSession()
  const pending = live && status.status === "pending"
  const [stage, setStage] = React.useState<Stage>(pending ? "submitted" : "form")
  const [submittedAt, setSubmittedAt] = React.useState<Date | null>(
    pending && status.submittedAt ? new Date(status.submittedAt) : null
  )
  const t = useTranslations("Account.accreditation")
  const f = useFormat()

  if (role === "journalist") {
    return (
      <div className="grid items-start gap-6 xl:grid-cols-2">
        <SettingsSection id="status" title={t("verifiedTitle")}>
          <div className="flex items-start gap-3 border border-verdict-authentic/40 bg-verdict-authentic/5 p-4">
            <RiVerifiedBadgeLine className="size-6 shrink-0 text-verdict-authentic" aria-hidden />
            <dl className="grid flex-1 grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
              <dt className="text-muted-foreground">{t("name")}</dt>
              <dd>{user?.name}</dd>
              <dt className="text-muted-foreground">{t("outlet")}</dt>
              <dd>{live ? (status.organisation ?? "—") : t("sampleOutlet")}</dd>
              <dt className="text-muted-foreground">{t("verified")}</dt>
              <dd>{live ? (status.reviewedAt ? f.date(status.reviewedAt) : "—") : f.date("2026-08-12")}</dd>
              {!live && (
                <>
                  <dt className="text-muted-foreground">{t("renews")}</dt>
                  <dd>{f.date("2027-08-12")}</dd>
                </>
              )}
            </dl>
          </div>
          <p className="text-sm text-muted-foreground">{t("changedNewsroom")}</p>
          <Button variant="outline" className="w-fit" onClick={() => toast.info(t("updateLater"))}>
            {t("updateDetails")}
          </Button>
        </SettingsSection>
        <SettingsSection id="benefits" title={t("benefitsTitle")}>
          <Benefits />
        </SettingsSection>
      </div>
    )
  }

  return (
    <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]">
      {stage === "form" ? (
        <ApplicationForm
          onSubmitted={() => {
            setSubmittedAt(new Date())
            setStage("submitted")
          }}
        />
      ) : (
        <SettingsSection
          id="application"
          title={t("receivedTitle")}
          footer={
            live ? undefined : (
              <Button
                variant="ghost"
                onClick={() => {
                  setStage("form")
                  toast.info(t("withdrawn"))
                }}
              >
                {t("withdraw")}
              </Button>
            )
          }
        >
          {submittedAt && <Timeline submittedAt={submittedAt} />}
        </SettingsSection>
      )}
      <SettingsSection id="benefits" title={t("whyTitle")} description={t("whyDescription")}>
        <Benefits />
      </SettingsSection>
    </div>
  )
}
