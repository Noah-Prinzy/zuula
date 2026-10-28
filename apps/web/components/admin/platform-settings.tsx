"use client"

import * as React from "react"
import { RiRestartLine } from "@remixicon/react"
import { useTranslations } from "next-intl"
import { toast } from "sonner"

import { SettingsSection } from "@/components/account/settings-section"
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
import { Button } from "@/components/ui/button"
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { Slider } from "@/components/ui/slider"
import { Skeleton } from "@/components/ui/skeleton"
import { useApiErrorMessage } from "@/hooks/use-api-error-message"
import { adminApi } from "@/lib/admin-api"
import { DEFAULT_SETTINGS, type PlatformSettings } from "@/lib/mock/admin"
import { cn } from "@/lib/utils"

import { useAdminData } from "./use-admin-data"

type Thresholds = PlatformSettings["thresholds"]

function NumberField({
  id,
  label,
  value,
  onChange,
  min,
  max,
  suffix,
  hint,
}: {
  id: string
  label: string
  value: number
  onChange: (v: number) => void
  min: number
  max: number
  suffix?: string
  hint?: string
}) {
  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <div className="flex items-center gap-2">
        <Input
          id={id}
          type="number"
          inputMode="numeric"
          min={min}
          max={max}
          value={value}
          onChange={(e) => onChange(Math.max(min, Math.min(max, Number(e.target.value) || 0)))}
          className="w-24 font-mono"
        />
        {suffix && <span className="text-sm text-muted-foreground">{suffix}</span>}
      </div>
      {hint && <FieldDescription>{hint}</FieldDescription>}
    </Field>
  )
}

function CcsSlider({ id, label, value, onChange, tone }: { id: string; label: string; value: number; onChange: (v: number) => void; tone: string }) {
  return (
    <Field>
      <div className="flex items-baseline justify-between">
        <FieldLabel htmlFor={id}>{label}</FieldLabel>
        <span className={cn("font-mono text-sm tabular-nums", tone)}>{value}%</span>
      </div>
      <Slider id={id} min={0} max={100} step={1} value={[value]} onValueChange={([v]) => onChange(v)} aria-label={label} />
    </Field>
  )
}

// Returns the Admin.settings.errors key for the first broken rule.
function validate(t: Thresholds) {
  if (!(t.suspendedMax < t.escalatedMax)) return "suspended" as const
  if (!(t.escalatedMax < t.questionedMin)) return "escalated" as const
  if (!(t.questionedMin <= t.questionedMax)) return "inverted" as const
  if (!(t.questionedMax < t.verifiedMin)) return "verified" as const
  if (!(t.questionedRatings <= t.escalatedRatings && t.escalatedRatings <= t.suspendedRatings)) return "ratings" as const
  return null
}

// FR-ADMIN-06: escalation thresholds, rating weights, SLA and retraining (§9.1–9.3).
// FR-ADMIN-06: the live settings come from the API (GET /admin/settings) and saving them is a
// PATCH the API validates and audits; demo builds edit the sample settings locally.
export function PlatformSettingsForm() {
  const { live, data } = useAdminData(adminApi.settings, DEFAULT_SETTINGS, [])
  if (!data) return <Skeleton className="h-96 w-full" />
  // The contract marks every nested field optional; the API always returns them all.
  return <SettingsForm live={live} initial={data as PlatformSettings} />
}

function SettingsForm({ live, initial }: { live: boolean; initial: PlatformSettings }) {
  const [s, setS] = React.useState<PlatformSettings>(initial)
  const [saved, setSaved] = React.useState<PlatformSettings>(initial)
  const [confirm, setConfirm] = React.useState(false)
  const errorMessage = useApiErrorMessage()
  const tr = useTranslations("Admin.settings")
  const tRoles = useTranslations("Roles")
  const tc = useTranslations("Common")
  const ta = useTranslations("Admin")
  const t = s.thresholds
  const setT = (patch: Partial<Thresholds>) => setS({ ...s, thresholds: { ...t, ...patch } })
  const error = validate(t)
  const dirty = JSON.stringify(s) !== JSON.stringify(saved)

  const changes = React.useMemo(() => {
    const out: string[] = []
    const walk = (a: Record<string, unknown>, b: Record<string, unknown>, path: string) => {
      for (const k of Object.keys(a)) {
        const av = a[k]
        const bv = b[k]
        if (typeof av === "object" && av !== null) walk(av as Record<string, unknown>, bv as Record<string, unknown>, `${path}${k}.`)
        else if (av !== bv) out.push(`${path}${k}: ${String(bv)} → ${String(av)}`)
      }
    }
    walk(s as unknown as Record<string, unknown>, saved as unknown as Record<string, unknown>, "")
    return out
  }, [s, saved])

  const footer = (
    <>
      {dirty && <span className="mr-auto text-xs text-muted-foreground">{tr("unsaved", { count: changes.length })}</span>}
      <Button variant="ghost" onClick={() => setS(DEFAULT_SETTINGS)} disabled={JSON.stringify(s) === JSON.stringify(DEFAULT_SETTINGS)}>
        <RiRestartLine aria-hidden /> {tr("specDefaults")}
      </Button>
      <Button onClick={() => setConfirm(true)} disabled={!dirty || !!error}>
        {tr("save")}
      </Button>
    </>
  )

  return (
    <div data-reveal="stagger" className="grid items-start gap-6 xl:grid-cols-2">
      <SettingsSection
        id="thresholds"
        title={tr("thresholdsTitle")}
        description={tr("thresholdsDescription")}
        footer={footer}
        className="xl:row-span-2"
      >
        <CcsSlider id="t-verified" label={tr("verifiedAt")} value={t.verifiedMin} onChange={(v) => setT({ verifiedMin: v })} tone="text-verdict-authentic" />
        <div className="grid gap-4 border-t pt-4 sm:grid-cols-[1fr_auto]">
          <div className="flex flex-col gap-4">
            <CcsSlider id="t-q-min" label={tr("questionedFrom")} value={t.questionedMin} onChange={(v) => setT({ questionedMin: v })} tone="text-verdict-likely-false" />
            <CcsSlider id="t-q-max" label={tr("questionedTo")} value={t.questionedMax} onChange={(v) => setT({ questionedMax: v })} tone="text-verdict-likely-false" />
          </div>
          <NumberField id="t-q-r" label={tr("withMoreThan")} value={t.questionedRatings} onChange={(v) => setT({ questionedRatings: v })} min={0} max={10000} suffix={tr("ratings")} />
        </div>
        <div className="grid gap-4 border-t pt-4 sm:grid-cols-[1fr_auto]">
          <CcsSlider id="t-e-max" label={tr("escalateAt")} value={t.escalatedMax} onChange={(v) => setT({ escalatedMax: v })} tone="text-verdict-false" />
          <NumberField id="t-e-r" label={tr("withMoreThan")} value={t.escalatedRatings} onChange={(v) => setT({ escalatedRatings: v })} min={0} max={10000} suffix={tr("ratings")} />
        </div>
        <div className="grid gap-4 border-t pt-4 sm:grid-cols-[1fr_auto]">
          <CcsSlider id="t-s-max" label={tr("suspendAt")} value={t.suspendedMax} onChange={(v) => setT({ suspendedMax: v })} tone="text-verdict-false" />
          <NumberField id="t-s-r" label={tr("withMoreThan")} value={t.suspendedRatings} onChange={(v) => setT({ suspendedRatings: v })} min={0} max={10000} suffix={tr("ratings")} />
        </div>
        {error && <FieldError>{tr(`errors.${error}`)}</FieldError>}
      </SettingsSection>

      <SettingsSection id="weights" title={tr("weightsTitle")} description={tr("weightsDescription")}>
        <div className="grid gap-4 sm:grid-cols-3">
          <NumberField id="w-public" label={tRoles("public")} value={s.weights.public} onChange={(v) => setS({ ...s, weights: { ...s.weights, public: v } })} min={1} max={10} suffix="×" />
          <NumberField id="w-journalist" label={tRoles("journalist")} value={s.weights.journalist} onChange={(v) => setS({ ...s, weights: { ...s.weights, journalist: v } })} min={1} max={10} suffix="×" />
          <NumberField id="w-expert" label={tRoles("expert")} value={s.weights.expert} onChange={(v) => setS({ ...s, weights: { ...s.weights, expert: v } })} min={1} max={10} suffix="×" />
        </div>
      </SettingsSection>

      <SettingsSection id="operations" title={tr("operationsTitle")} description={tr("operationsDescription")}>
        <div className="grid gap-4 sm:grid-cols-2">
          <NumberField id="sla" label={tr("sla")} value={s.slaHours} onChange={(v) => setS({ ...s, slaHours: v })} min={1} max={168} suffix={tr("hours")} hint={tr("slaHint")} />
          <NumberField id="rate" label={tr("rateLimit")} value={s.apiRateLimit} onChange={(v) => setS({ ...s, apiRateLimit: v })} min={10} max={10000} suffix={tr("perHour")} hint={tr("rateHint")} />
          <Field>
            <FieldLabel htmlFor="retrain">{tr("retraining")}</FieldLabel>
            <NativeSelect id="retrain" className="w-full" value={s.retraining.cadence} onChange={(e) => setS({ ...s, retraining: { ...s.retraining, cadence: e.target.value as "weekly" | "monthly" } })}>
              <NativeSelectOption value="weekly">{tr("weekly")}</NativeSelectOption>
              <NativeSelectOption value="monthly">{tr("monthly")}</NativeSelectOption>
            </NativeSelect>
          </Field>
          <NumberField id="min-ccs" label={tr("minCcs")} value={s.retraining.minCcs} onChange={(v) => setS({ ...s, retraining: { ...s.retraining, minCcs: v } })} min={50} max={100} suffix="%" hint={tr("minCcsHint")} />
        </div>
      </SettingsSection>

      <AlertDialog open={confirm} onOpenChange={setConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{tr("confirmTitle", { count: changes.length })}</AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="flex flex-col gap-2">
                <span>{tr("confirmBody")}</span>
                <ul className="max-h-48 overflow-y-auto border bg-muted/40 p-2 font-mono text-xs">
                  {changes.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{tc("cancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={async () => {
                try {
                  setSaved(live ? ((await adminApi.updateSettings(s)) as PlatformSettings) : s)
                  toast.success(tr("saved"), { description: ta("loggedInAudit") })
                } catch (e) {
                  toast.error(errorMessage(e))
                }
              }}
            >
              {tc("save")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
