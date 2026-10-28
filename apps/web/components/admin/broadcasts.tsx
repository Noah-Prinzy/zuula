"use client"

import * as React from "react"
import { RiAlarmWarningLine, RiMegaphoneLine, RiSendPlaneLine } from "@remixicon/react"
import { useTranslations } from "next-intl"
import { toast } from "sonner"

import { SettingsSection } from "@/components/account/settings-section"
import { NotificationIcon } from "@/components/account/notification-icon"
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
import { Field, FieldDescription, FieldError, FieldLabel, FieldLegend, FieldSet } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { Textarea } from "@/components/ui/textarea"
import { SAMPLE_REPORTS } from "@/lib/mock/fact-checks"
import { Skeleton } from "@/components/ui/skeleton"
import { useApiErrorMessage } from "@/hooks/use-api-error-message"
import { adminApi } from "@/lib/admin-api"
import { SAMPLE_BROADCASTS, type Broadcast } from "@/lib/mock/admin"
import { useSession } from "@/components/providers/session-provider"
import { useFormat } from "@/lib/format"
import { cn } from "@/lib/utils"

import { useAdminData } from "./use-admin-data"

// Channel ids double as the stored values; labels live in Admin.broadcasts.channels.
const CHANNELS = ["In-app", "Push", "Email", "SMS", "WhatsApp"] as const
const AUDIENCES = [
  { value: "everyone", estimate: 52_000 },
  { value: "central", estimate: 18_500 },
  { value: "northern", estimate: 9_200 },
  { value: "eastern", estimate: 11_400 },
  { value: "western", estimate: 12_900 },
  { value: "health", estimate: 14_300 },
  { value: "elections", estimate: 10_800 },
] as const
const MAX_MESSAGE = 320 // fits two SMS segments
// The API's channel ids (POST /admin/broadcasts). It has no WhatsApp broadcast yet.
const API_CHANNELS: Partial<Record<(typeof CHANNELS)[number], "in-app" | "push" | "email" | "sms">> = {
  "In-app": "in-app",
  Push: "push",
  Email: "email",
  SMS: "sms",
}

function useChannelList() {
  const t = useTranslations("Admin.broadcasts.channels")
  return (channels: string[]) =>
    channels.map((c) => (t.has(c as (typeof CHANNELS)[number]) ? t(c as (typeof CHANNELS)[number]) : c)).join(", ")
}

function Composer({ live, onSent }: { live: boolean; onSent: (b: Broadcast) => void }) {
  const { user } = useSession()
  const errorMessage = useApiErrorMessage()
  const [title, setTitle] = React.useState("")
  const [message, setMessage] = React.useState("")
  const [reportId, setReportId] = React.useState("")
  const [severity, setSeverity] = React.useState<"high" | "critical">("high")
  const [audience, setAudience] = React.useState<(typeof AUDIENCES)[number]["value"]>("everyone")
  const [channels, setChannels] = React.useState<string[]>(["In-app", "Push"])
  const [errors, setErrors] = React.useState<Record<string, string>>({})
  const [confirm, setConfirm] = React.useState(false)
  const t = useTranslations("Admin.broadcasts")
  const tc = useTranslations("Common")
  const f = useFormat()
  const channelList = useChannelList()

  const aud = AUDIENCES.find((a) => a.value === audience)!
  const audLabel = t(`audiences.${aud.value}`)

  function review(e: React.FormEvent) {
    e.preventDefault()
    const next: Record<string, string> = {}
    if (title.trim().length < 8) next.title = t("errors.title")
    if (message.trim().length < 30) next.message = t("errors.message")
    if (channels.length === 0) next.channels = t("errors.channels")
    setErrors(next)
    if (Object.keys(next).length === 0) setConfirm(true)
  }

  async function send() {
    if (live) {
      const apiChannels = channels.flatMap((c) => API_CHANNELS[c as (typeof CHANNELS)[number]] ?? [])
      try {
        onSent(
          await adminApi.sendBroadcast({ title: title.trim(), message: message.trim(), severity, audience: audLabel, channels: apiChannels })
        )
      } catch (e) {
        toast.error(errorMessage(e))
        return
      }
    } else {
      onSent({
        id: crypto.randomUUID(),
        title: title.trim(),
        message: message.trim(),
        severity,
        audience: audLabel,
        channels,
        sentAt: new Date().toISOString(),
        sentBy: user?.name ?? t("administrator"),
        reach: aud.estimate,
        opened: 0,
      })
    }
    toast.success(t("sent"), { description: t("sentSummary", { count: f.number(aud.estimate), channels: channelList(channels) }) })
    setTitle("")
    setMessage("")
    setReportId("")
  }

  return (
    <form noValidate onSubmit={review} className="contents">
      <SettingsSection
        id="compose"
        title={t("composeTitle")}
        description={t("composeDescription")}
        footer={
          <Button type="submit">
            <RiSendPlaneLine aria-hidden /> {t("reviewAndSend")}
          </Button>
        }
      >
        <Field data-invalid={!!errors.title}>
          <FieldLabel htmlFor="bc-title">{t("headline")}</FieldLabel>
          <Input id="bc-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={90} placeholder={t("headlinePlaceholder")} />
          {errors.title && <FieldError>{errors.title}</FieldError>}
        </Field>
        <Field data-invalid={!!errors.message}>
          <FieldLabel htmlFor="bc-message">{t("message")}</FieldLabel>
          <Textarea id="bc-message" rows={4} value={message} onChange={(e) => setMessage(e.target.value)} maxLength={MAX_MESSAGE} placeholder={t("messagePlaceholder")} />
          <FieldDescription className="text-right tabular-nums">{t("messageCount", { count: message.length, max: MAX_MESSAGE })}</FieldDescription>
          {errors.message && <FieldError>{errors.message}</FieldError>}
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field>
            <FieldLabel htmlFor="bc-report">{t("linkReport")}</FieldLabel>
            <NativeSelect id="bc-report" className="w-full" value={reportId} onChange={(e) => setReportId(e.target.value)}>
              <NativeSelectOption value="">{t("none")}</NativeSelectOption>
              {SAMPLE_REPORTS.slice(0, 8).map((r) => (
                <NativeSelectOption key={r.id} value={r.id}>{r.title.replace(/[“”]/g, "")}</NativeSelectOption>
              ))}
            </NativeSelect>
          </Field>
          <Field>
            <FieldLabel htmlFor="bc-audience">{t("audience")}</FieldLabel>
            <NativeSelect id="bc-audience" className="w-full" value={audience} onChange={(e) => setAudience(e.target.value as (typeof AUDIENCES)[number]["value"])}>
              {AUDIENCES.map((a) => (
                <NativeSelectOption key={a.value} value={a.value}>{t(`audiences.${a.value}`)}</NativeSelectOption>
              ))}
            </NativeSelect>
            <FieldDescription>{t("audienceEstimate", { count: f.number(aud.estimate) })}</FieldDescription>
          </Field>
        </div>
        <FieldSet>
          <FieldLegend variant="label">{t("severity")}</FieldLegend>
          <RadioGroup value={severity} onValueChange={(v) => setSeverity(v as "high" | "critical")} className="flex flex-wrap gap-4">
            <label className="flex items-center gap-2 text-sm">
              <RadioGroupItem value="high" /> {t("severityHigh")}
            </label>
            <label className="flex items-center gap-2 text-sm">
              <RadioGroupItem value="critical" /> {t("severityCritical")}
            </label>
          </RadioGroup>
        </FieldSet>
        <FieldSet data-invalid={!!errors.channels}>
          <FieldLegend variant="label">{t("channelsLegend")}</FieldLegend>
          <div className="flex flex-wrap gap-4">
            {(live ? CHANNELS.filter((c) => API_CHANNELS[c]) : CHANNELS).map((c) => (
              <label key={c} className="flex items-center gap-2 text-sm">
                <Checkbox checked={channels.includes(c)} onCheckedChange={(on) => setChannels((cs) => (on === true ? [...cs, c] : cs.filter((x) => x !== c)))} />
                {t(`channels.${c}`)}
              </label>
            ))}
          </div>
          {errors.channels && <FieldError>{errors.channels}</FieldError>}
        </FieldSet>

        <div className="flex flex-col gap-2 border-t pt-4">
          <span className="text-xs text-muted-foreground">{t("preview")}</span>
          <div className={cn("flex gap-3 border p-3", severity === "critical" ? "border-verdict-false/50 bg-verdict-false/5" : "bg-muted/30")}>
            <NotificationIcon kind="broadcast" />
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="text-sm font-semibold">{title || t("previewTitle")}</span>
              <span className="text-sm text-muted-foreground">{message || t("previewBody")}</span>
            </div>
          </div>
        </div>
      </SettingsSection>

      <AlertDialog open={confirm} onOpenChange={setConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("confirmTitle", { count: f.number(aud.estimate) })}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("confirmBody", { audience: audLabel, channels: channelList(channels), severity: t(`severities.${severity}`) })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{tc("goBack")}</AlertDialogCancel>
            <AlertDialogAction onClick={send} className="bg-destructive text-white hover:bg-destructive/90">
              {t("send")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </form>
  )
}

// FR-ADMIN-05: emergency broadcasts about high-priority misinformation.
// FR-ADMIN-03: urgent alerts. Live, sending goes to the API (POST /admin/broadcasts, audited and
// delivered by the worker) and the history is GET /admin/broadcasts; demo builds keep both local.
export function Broadcasts() {
  const { live, data } = useAdminData(adminApi.broadcasts, SAMPLE_BROADCASTS, [])
  if (!data) return <Skeleton className="h-96 w-full" />
  return <BroadcastsView live={live} initial={data} />
}

function BroadcastsView({ live, initial }: { live: boolean; initial: Broadcast[] }) {
  const [sent, setSent] = React.useState(initial)
  const t = useTranslations("Admin.broadcasts")
  const f = useFormat()
  const channelList = useChannelList()
  return (
    <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_28rem]">
      <Composer live={live} onSent={(b) => setSent((s) => [b, ...s])} />
      <section data-reveal aria-labelledby="sent-title" className="flex flex-col gap-3 [--d:1]">
        <h2 id="sent-title" className="flex items-center gap-2 font-heading text-lg font-bold">
          <RiMegaphoneLine className="size-5 text-primary" aria-hidden /> {t("sentTitle")}
        </h2>
        <ul className="flex flex-col divide-y border bg-card">
          {sent.map((b) => (
            <li key={b.id} className="flex flex-col gap-1.5 p-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={b.severity === "critical" ? "destructive" : "secondary"} className="gap-1">
                  <RiAlarmWarningLine aria-hidden /> {t(`severities.${b.severity}`)}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  {f.dateTime(b.sentAt)} · {b.sentBy}
                </span>
              </div>
              <span className="font-medium">{b.title}</span>
              <span className="text-sm text-muted-foreground">{b.message}</span>
              <span className="text-xs text-muted-foreground">
                {t("reached", { audience: b.audience, channels: channelList(b.channels), count: f.number(b.reach) })}
                {b.opened > 0 && t("opened", { percent: Math.round((b.opened / b.reach) * 100) })}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
