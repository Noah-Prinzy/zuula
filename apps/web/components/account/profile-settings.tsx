"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import {
  RiComputerLine,
  RiDeleteBin6Line,
  RiDownload2Line,
  RiShieldCheckLine,
  RiSmartphoneLine,
} from "@remixicon/react"
import { useTranslations } from "next-intl"
import { toast } from "sonner"

import { PasswordInput } from "@/components/auth/password-input"
import { PasswordStrength } from "@/components/auth/password-strength"
import { CodeInput } from "@/components/auth/code-input"
import { SettingsSection } from "@/components/account/settings-section"
import { useSession } from "@/components/providers/session-provider"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { Switch } from "@/components/ui/switch"
import { useApiErrorMessage } from "@/hooks/use-api-error-message"
import { useLiveData } from "@/hooks/use-live-data"
import { useRelativeTime } from "@/hooks/use-relative-time"
import { accountApi, accountApiLive } from "@/lib/account-api"
import { authApi, authMode } from "@/lib/api"
import { identifierKind, PASSWORD_MIN, passwordStrength } from "@/lib/auth"
import { LOCALES, type LocaleCode } from "@/lib/locales"
import { isDemoCodeValid, SAMPLE_RATINGS, SAMPLE_SESSIONS, SAMPLE_SUBMISSIONS } from "@/lib/mock/account"
import { changeSupabasePassword } from "@/lib/supabase-auth"
import { initials } from "@/lib/utils"

// FR-ACCOUNT. Live, everything here goes through the API: details (PATCH /me), password,
// two-factor, devices (GET/DELETE /me/sessions), data export and erasure. With Supabase
// sign-in the password and the email address belong to Supabase, so the password is changed
// there and the address isn't edited here. Demo builds change nothing outside this page.

function DetailsSection() {
  const { user, locale, setLocale, refresh } = useSession()
  const live = accountApiLive()
  // Phone and district aren't in the session; the API's profile has them.
  const { data: me } = useLiveData(live, authApi.me, null, [])
  const errorMessage = useApiErrorMessage()
  const [name, setName] = React.useState(user?.name ?? "")
  const [email, setEmail] = React.useState(user?.email ?? "")
  const [phone, setPhone] = React.useState("")
  const [district, setDistrict] = React.useState("Kampala")
  const [loadedMe, setLoadedMe] = React.useState(false)
  if (me && !loadedMe) {
    setLoadedMe(true)
    setPhone(me.phone ?? "")
    if (me.district) setDistrict(me.district)
  }
  const [lang, setLang] = React.useState<LocaleCode>(locale)
  const [errors, setErrors] = React.useState<Record<string, string>>({})
  const t = useTranslations("Account.profile")
  const tc = useTranslations("Common")
  const tr = useTranslations("Roles")

  async function save(e: React.FormEvent) {
    e.preventDefault()
    const next: Record<string, string> = {}
    if (name.trim().length < 2) next.name = t("errors.name")
    if (email && identifierKind(email) !== "email") next.email = t("errors.email")
    if (phone && identifierKind(phone) !== "phone") next.phone = t("errors.phone")
    if (!email && !phone) next.email = t("errors.contact")
    setErrors(next)
    if (Object.keys(next).length) return
    if (live) {
      try {
        await accountApi.updateMe({
          name: name.trim(),
          district,
          preferredLanguage: lang,
          ...(authMode() === "supabase" ? {} : { email: email.trim() || undefined, phone: phone.trim() || undefined }),
        })
        await refresh()
      } catch (err) {
        toast.error(errorMessage(err))
        return
      }
    }
    setLocale(lang)
    toast.success(t("saved"))
  }

  return (
    <form noValidate onSubmit={save} className="contents">
      <SettingsSection
        id="details"
        title={t("detailsTitle")}
        description={t("detailsDescription")}
        footer={<Button type="submit">{tc("saveChanges")}</Button>}
      >
        <div className="flex items-center gap-3">
          <Avatar className="size-12">
            <AvatarFallback className="text-base">{initials(name || "?")}</AvatarFallback>
          </Avatar>
          <div className="flex flex-col">
            <span className="font-medium">{name || "—"}</span>
            {user && (
              <Badge variant="outline" className="w-fit">
                {tr(user.role)}
              </Badge>
            )}
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field data-invalid={!!errors.name} className="sm:col-span-2">
            <FieldLabel htmlFor="profile-name">{t("fullName")}</FieldLabel>
            <Input id="profile-name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" aria-invalid={!!errors.name} />
            {errors.name && <FieldError>{errors.name}</FieldError>}
          </Field>
          <Field data-invalid={!!errors.email}>
            <FieldLabel htmlFor="profile-email">{t("email")}</FieldLabel>
            <Input id="profile-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" aria-invalid={!!errors.email} />
            {errors.email && <FieldError>{errors.email}</FieldError>}
          </Field>
          <Field data-invalid={!!errors.phone}>
            <FieldLabel htmlFor="profile-phone">{t("phone")}</FieldLabel>
            <Input id="profile-phone" type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} autoComplete="tel" placeholder="07XX XXX XXX" aria-invalid={!!errors.phone} />
            {errors.phone && <FieldError>{errors.phone}</FieldError>}
          </Field>
          <Field>
            <FieldLabel htmlFor="profile-language">{t("language")}</FieldLabel>
            <NativeSelect id="profile-language" className="w-full" value={lang} onChange={(e) => setLang(e.target.value as LocaleCode)}>
              {LOCALES.map((l) => (
                <NativeSelectOption key={l.code} value={l.code}>
                  {l.label}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <FieldDescription>{t("languageHint")}</FieldDescription>
          </Field>
          <Field>
            <FieldLabel htmlFor="profile-district">{t("district")}</FieldLabel>
            <Input id="profile-district" value={district} onChange={(e) => setDistrict(e.target.value)} />
            <FieldDescription>{t("districtHint")}</FieldDescription>
          </Field>
        </div>
      </SettingsSection>
    </form>
  )
}

function PasswordDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const [current, setCurrent] = React.useState("")
  const [next, setNext] = React.useState("")
  const [confirm, setConfirm] = React.useState("")
  const [error, setError] = React.useState<string | null>(null)
  const t = useTranslations("Account.profile.password")
  const tc = useTranslations("Common")

  function reset() {
    setCurrent("")
    setNext("")
    setConfirm("")
    setError(null)
  }

  const errorMessage = useApiErrorMessage()

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!current) return setError(t("currentRequired"))
    if (next.length < PASSWORD_MIN || passwordStrength(next).score < 3)
      return setError(t("weak", { min: PASSWORD_MIN }))
    if (next !== confirm) return setError(t("mismatch"))
    if (next === current) return setError(t("reused"))
    if (accountApiLive()) {
      try {
        if (authMode() === "supabase") await changeSupabasePassword(current, next)
        else await accountApi.changePassword({ currentPassword: current, newPassword: next })
      } catch (err) {
        return setError(errorMessage(err))
      }
    }
    onOpenChange(false)
    reset()
    toast.success(t("changed"), { description: t("changedBody") })
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        onOpenChange(o)
        if (!o) reset()
      }}
    >
      <DialogContent>
        <form noValidate onSubmit={submit} className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle>{t("title")}</DialogTitle>
            <DialogDescription>{t("description")}</DialogDescription>
          </DialogHeader>
          <Field>
            <FieldLabel htmlFor="pw-current">{t("current")}</FieldLabel>
            <PasswordInput id="pw-current" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" />
          </Field>
          <Field>
            <FieldLabel htmlFor="pw-new">{t("new")}</FieldLabel>
            <PasswordInput id="pw-new" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" aria-describedby="pw-new-strength" />
            <PasswordStrength id="pw-new-strength" password={next} />
          </Field>
          <Field data-invalid={!!error}>
            <FieldLabel htmlFor="pw-confirm">{t("confirm")}</FieldLabel>
            <PasswordInput id="pw-confirm" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" />
            {error && <FieldError>{error}</FieldError>}
          </Field>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {tc("cancel")}
            </Button>
            <Button type="submit">{t("title")}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// Placeholder setup key; the real one (and QR code) comes from the auth API.
const DEMO_SECRET = "JBSW Y3DP EHPK 3PXP"

function TwoFactorDialog({
  open,
  onOpenChange,
  onEnabled,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  onEnabled: () => void
}) {
  const [code, setCode] = React.useState("")
  const [error, setError] = React.useState<string | null>(null)
  const t = useTranslations("Account.profile.tfa")
  const tc = useTranslations("Common")

  function confirm(value = code) {
    if (!isDemoCodeValid(value)) {
      setError(t("mismatch"))
      setCode("")
      return
    }
    setCode("")
    setError(null)
    onEnabled()
    onOpenChange(false)
    toast.success(t("enabled"), { description: t("enabledBody") })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-2 border bg-muted/40 p-3">
          <span className="text-xs text-muted-foreground">{t("setupKey")}</span>
          <code className="font-mono text-lg tracking-widest">{DEMO_SECRET}</code>
        </div>
        <Field data-invalid={!!error}>
          <FieldLabel htmlFor="tfa-setup-code">{t("code")}</FieldLabel>
          <CodeInput
            id="tfa-setup-code"
            value={code}
            onChange={(v) => {
              setCode(v)
              if (error) setError(null)
            }}
            onComplete={confirm}
            invalid={!!error}
          />
          {error ? <FieldError>{error}</FieldError> : <FieldDescription>{t("demoHint")}</FieldDescription>}
        </Field>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {tc("cancel")}
          </Button>
          <Button onClick={() => confirm()}>{t("turnOn")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function SecuritySection() {
  const { role } = useSession()
  const required = role === "expert" || role === "admin"
  const [pwOpen, setPwOpen] = React.useState(false)
  const [tfaOpen, setTfaOpen] = React.useState(false)
  const live = accountApiLive()
  const [tfaOn, setTfaOn] = React.useState(required)
  const loaded = useLiveData(live, accountApi.sessions, SAMPLE_SESSIONS, [])
  const [removed, setRemoved] = React.useState<string[]>([])
  const sessions = (loaded.data ?? []).filter((d) => !removed.includes(d.id))
  const errorMessage = useApiErrorMessage()
  const relativeTime = useRelativeTime()

  // Live, signing a device out revokes its session; the list then drops it.
  async function signOutOf(ids: string[]) {
    if (live) {
      try {
        await Promise.all(ids.map((id) => accountApi.revokeSession(id)))
      } catch (e) {
        toast.error(errorMessage(e))
        return false
      }
    }
    setRemoved((r) => [...r, ...ids])
    return true
  }

  async function setTwoFactor(on: boolean) {
    if (!live) {
      if (on) setTfaOpen(true)
      else {
        setTfaOn(false)
        toast.info(t("tfa.disabled"))
      }
      return
    }
    try {
      await accountApi.setTwoFactor({ enabled: on })
    } catch (e) {
      toast.error(errorMessage(e))
      return
    }
    setTfaOn(on)
    if (on) toast.success(t("tfa.enabled"), { description: t("tfa.enabledBody") })
    else toast.info(t("tfa.disabled"))
  }
  const t = useTranslations("Account.profile")
  const tr = useTranslations("Roles")

  return (
    <SettingsSection id="security" title={t("securityTitle")} description={t("securityDescription")}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium">{t("passwordLabel")}</p>
          {/* A sample date: the API doesn't record when a password last changed. */}
          {!live && <p className="text-xs text-muted-foreground">{t("passwordAge")}</p>}
        </div>
        <Button variant="outline" onClick={() => setPwOpen(true)}>
          {t("password.title")}
        </Button>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
        <div className="flex flex-col gap-0.5">
          <label htmlFor="tfa-switch" className="flex items-center gap-2 text-sm font-medium">
            <RiShieldCheckLine className="size-4 text-primary" aria-hidden />
            {t("tfa.label")}
          </label>
          <p className="text-xs text-muted-foreground">
            {required ? t("tfa.required", { role: tr(role!) }) : t("tfa.optional")}
          </p>
        </div>
        <Switch
          id="tfa-switch"
          checked={tfaOn}
          disabled={required}
          onCheckedChange={(on) => void setTwoFactor(on)}
        />
      </div>

      <div className="flex flex-col gap-2 border-t pt-4">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-medium">{t("devices")}</p>
          {sessions.length > 1 && (
            <Button
              variant="link"
              size="xs"
              className="px-0"
              onClick={async () => {
                if (await signOutOf(sessions.filter((d) => !d.current).map((d) => d.id)))
                  toast.success(t("signedOutOthers"))
              }}
            >
              {t("signOutOthers")}
            </Button>
          )}
        </div>
        <ul className="flex flex-col divide-y border">
          {sessions.map((d) => {
            const Icon = /android|iphone|app/i.test(d.device) ? RiSmartphoneLine : RiComputerLine
            return (
              <li key={d.id} className="flex items-center gap-3 p-3">
                <Icon className="size-5 shrink-0 text-muted-foreground" aria-hidden />
                <div className="flex min-w-0 flex-1 flex-col">
                  <span className="text-sm">
                    {d.device}
                    {d.current && <Badge variant="secondary" className="ml-2">{t("thisDevice")}</Badge>}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {d.location} · {/^\d{4}-/.test(d.lastActive) ? relativeTime(d.lastActive) : d.lastActive}
                  </span>
                </div>
                {!d.current && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={async () => {
                      if (await signOutOf([d.id])) toast.success(t("signedOutOf", { device: d.device }))
                    }}
                  >
                    {t("signOut")}
                  </Button>
                )}
              </li>
            )
          })}
        </ul>
      </div>

      <PasswordDialog open={pwOpen} onOpenChange={setPwOpen} />
      <TwoFactorDialog open={tfaOpen} onOpenChange={setTfaOpen} onEnabled={() => setTfaOn(true)} />
    </SettingsSection>
  )
}

function DataSection() {
  const router = useRouter()
  const { user, signOut } = useSession()
  const [confirmText, setConfirmText] = React.useState("")
  const t = useTranslations("Account.profile")
  const tc = useTranslations("Common")

  const errorMessage = useApiErrorMessage()

  // DPPA 2019 right of access: everything we hold about the user as a JSON file.
  async function exportData() {
    if (accountApiLive()) {
      try {
        download(await accountApi.exportData())
      } catch (e) {
        toast.error(errorMessage(e))
      }
      return
    }
    download({
      exportedAt: new Date().toISOString(),
      profile: user,
      submissions: SAMPLE_SUBMISSIONS,
      ratings: SAMPLE_RATINGS,
      note: "Sample export. The real export is generated by the server.",
    })
  }

  function download(data: unknown) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }))
    const a = document.createElement("a")
    a.href = url
    a.download = "zuula-my-data.json"
    a.click()
    URL.revokeObjectURL(url)
    toast.success(t("downloading"))
  }

  return (
    <SettingsSection
      id="your-data"
      title={t("dataTitle")}
      description={t("dataDescription")}
      tone="danger"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium">{t("downloadTitle")}</p>
          <p className="text-xs text-muted-foreground">{t("downloadBody")}</p>
        </div>
        <Button variant="outline" onClick={exportData}>
          <RiDownload2Line aria-hidden /> {t("download")}
        </Button>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
        <div className="max-w-xl">
          <p className="text-sm font-medium">{t("deleteTitle")}</p>
          <p className="text-xs text-muted-foreground">{t("deleteBody")}</p>
        </div>
        <AlertDialog onOpenChange={(o) => !o && setConfirmText("")}>
          <AlertDialogTrigger asChild>
            <Button variant="destructive">
              <RiDeleteBin6Line aria-hidden /> {t("deleteAccount")}
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>{t("deleteConfirmTitle")}</AlertDialogTitle>
              <AlertDialogDescription>
                {t.rich("deleteConfirmBody", { strong: (chunks) => <strong>{chunks}</strong> })}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <Input
              aria-label={t("deleteConfirmLabel")}
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              autoComplete="off"
            />
            <AlertDialogFooter>
              <AlertDialogCancel>{tc("cancel")}</AlertDialogCancel>
              <AlertDialogAction
                disabled={confirmText !== "DELETE"}
                className="bg-destructive text-white hover:bg-destructive/90"
                onClick={async () => {
                  // Live, DELETE /me erases the account (anonymised; ratings and the audit
                  // trail keep their shape). Demo builds only sign out.
                  if (accountApiLive()) {
                    try {
                      await accountApi.deleteMe()
                    } catch (e) {
                      toast.error(errorMessage(e))
                      return
                    }
                  }
                  void signOut().catch(() => {})
                  toast.success(t("deleted"), { description: t("deletedBody") })
                  router.push("/")
                }}
              >
                {t("deleteAccount")}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </SettingsSection>
  )
}

export function ProfileSettings() {
  const { user, role } = useSession()
  // Re-initialise the forms once the session is known (it loads after first render).
  return (
    <div className="grid items-start gap-6 xl:grid-cols-2">
      <DetailsSection key={user?.email ?? "anon"} />
      <SecuritySection key={role ?? "anon"} />
      <DataSection />
    </div>
  )
}
