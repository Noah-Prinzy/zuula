"use client"

import * as React from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { RiShieldKeyholeLine } from "@remixicon/react"
import { useTranslations } from "next-intl"
import { toast } from "sonner"

import { AuthHeading } from "@/components/auth/auth-heading"
import { DemoHint } from "@/components/auth/demo-hint"
import { CodeInput } from "@/components/auth/code-input"
import { ResendCode } from "@/components/auth/resend-code"
import { usePendingAuth } from "@/components/auth/use-pending-auth"
import { useSession } from "@/components/providers/session-provider"
import { startNavigationProgress } from "@/components/shell/route-progress"
import { Button } from "@/components/ui/button"
import { Field, FieldError, FieldLabel } from "@/components/ui/field"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { useApiErrorMessage } from "@/hooks/use-api-error-message"
import { authApi } from "@/lib/api"
import { clearPendingAuth, homeFor, safeNext } from "@/lib/auth"

// FR-AUTH-05: second factor for Expert Reviewers, Administrators and anyone who opted in. The
// API sends a one-time code by SMS (or email when the account has no phone) and returns a
// challenge id from sign-in; this screen completes that challenge. There are no authenticator
// apps or backup codes in the API yet, so neither is offered here.
// `challenge` comes from the URL when Google/Facebook sign-in needs a second factor: the API's
// OAuth callback redirects to /sign-in/two-factor?challenge=…, with nothing in sessionStorage.
export function TwoFactorForm({ challenge }: { challenge?: string }) {
  const router = useRouter()
  const { setAccount } = useSession()
  const t = useTranslations("Auth")
  const tv = useTranslations("Validation")
  const tr = useTranslations("Roles")
  const apiMessage = useApiErrorMessage()
  const pending = usePendingAuth()
  const [code, setCode] = React.useState("")
  const [error, setError] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)

  if (pending === undefined) return <Skeleton className="h-80 w-full" />
  const challengeId = pending?.challengeId ?? challenge
  if (!challengeId) {
    return (
      <div className="flex flex-col gap-4">
        <AuthHeading title={t("twoFactor.signInFirstTitle")} description={t("twoFactor.signInFirstBody")} />
        <Button asChild className="w-fit">
          <Link href="/sign-in">{t("twoFactor.goToSignIn")}</Link>
        </Button>
      </div>
    )
  }
  const destination = pending?.maskedIdentifier ?? t("twoFactor.yourAccount")

  async function submit(value = code) {
    if (value.length < 6) {
      setError(tv("codeAllDigits"))
      return
    }
    setBusy(true)
    setError(null)
    let user
    try {
      user = (await authApi.verifyTwoFactor({ challengeId: challengeId!, code: value })).user
    } catch (e) {
      setBusy(false)
      setError(apiMessage(e))
      setCode("")
      return
    }
    clearPendingAuth()
    setAccount(user)
    toast.success(t("twoFactor.toastTitle"), { description: tr(user.role) })
    startNavigationProgress()
    router.push(safeNext(pending?.next, homeFor(user.role)))
  }

  return (
    <div className="flex flex-col gap-6">
      <AuthHeading
        icon={RiShieldKeyholeLine}
        title={t("twoFactor.title")}
        description={t.rich("twoFactor.sentTo", {
          destination,
          strong: (chunks) => <span className="font-medium text-foreground">{chunks}</span>,
        })}
      />

      <DemoHint kind="code" />
      <form
        noValidate
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
        className="flex flex-col gap-4"
      >
        <Field data-invalid={!!error}>
          <FieldLabel htmlFor="tfa-code">{t("twoFactor.codeLabel")}</FieldLabel>
          <CodeInput
            id="tfa-code"
            value={code}
            onChange={(next) => {
              setCode(next)
              if (error) setError(null)
            }}
            onComplete={(next) => void submit(next)}
            invalid={!!error}
            disabled={busy}
            describedBy={error ? "tfa-error" : undefined}
          />
          {error && <FieldError id="tfa-error">{error}</FieldError>}
        </Field>

        <Button type="submit" size="lg" className="h-10" disabled={busy}>
          {busy && <Spinner />}
          {busy ? t("twoFactor.submitting") : t("twoFactor.submit")}
        </Button>
      </form>

      <div className="flex flex-col gap-1 text-sm text-muted-foreground">
        <ResendCode destination={destination} onResend={() => authApi.resendTwoFactor({ challengeId })} />
        <p>
          {t("twoFactor.cantReceive")}{" "}
          <Link href="/about#contact" className="text-primary underline underline-offset-4">
            {t("twoFactor.contactAdmin")}
          </Link>
        </p>
      </div>
    </div>
  )
}
