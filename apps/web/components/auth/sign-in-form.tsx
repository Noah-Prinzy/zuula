"use client"

import * as React from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { zodResolver } from "@hookform/resolvers/zod"
import { useTranslations } from "next-intl"
import { Controller, useForm } from "react-hook-form"
import { toast } from "sonner"
import type { z } from "zod"

import { AuthHeading } from "@/components/auth/auth-heading"
import { DemoHint } from "@/components/auth/demo-hint"
import { FormError } from "@/components/auth/form-error"
import { PasswordInput } from "@/components/auth/password-input"
import { SocialButtons } from "@/components/auth/social-buttons"
import { useSession } from "@/components/providers/session-provider"
import { startNavigationProgress } from "@/components/shell/route-progress"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Field, FieldError, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Spinner } from "@/components/ui/spinner"
import { useApiErrorMessage } from "@/hooks/use-api-error-message"
import { useValidationMessage } from "@/hooks/use-validation-message"
import { authApi, isTwoFactorChallenge } from "@/lib/api"
import { homeFor, safeNext, setPendingAuth, signInSchema } from "@/lib/auth"

type Values = z.infer<typeof signInSchema>

// Reasons the API's OAuth callback sends back as /sign-in?error=… (apps/api/app/api/v1/auth.py).
const OAUTH_ERRORS = ["oauth", "oauth-unavailable", "suspended"] as const

export function SignInForm({ next, oauthError }: { next?: string; oauthError?: string }) {
  const router = useRouter()
  const { setAccount } = useSession()
  const t = useTranslations("Auth")
  const tr = useTranslations("Roles")
  const v = useValidationMessage()
  const apiMessage = useApiErrorMessage()
  const ts = useTranslations("Auth.social.errors")
  const [error, setError] = React.useState<string | null>(() => {
    const reason = OAUTH_ERRORS.find((r) => r === oauthError)
    return reason ? ts(reason) : null
  })
  const form = useForm<Values>({
    resolver: zodResolver(signInSchema),
    defaultValues: { identifier: "", password: "", remember: true },
  })
  const { control, handleSubmit, formState } = form

  async function onSubmit(values: Values) {
    setError(null)
    let result
    try {
      result = await authApi.signIn({
        identifier: values.identifier.trim(),
        password: values.password,
        remember: values.remember,
      })
    } catch (e) {
      setError(apiMessage(e))
      return
    }
    startNavigationProgress()

    // FR-AUTH-05: the API asks Expert Reviewers, Admins and opted-in users for a second factor.
    if (isTwoFactorChallenge(result)) {
      setPendingAuth({
        identifier: values.identifier.trim(),
        next: safeNext(next, "") || undefined,
        challengeId: result.challengeId,
        maskedIdentifier: result.maskedIdentifier,
      })
      router.push("/sign-in/two-factor")
      return
    }
    const { user } = result
    setAccount(user)
    toast.success(t("signIn.toastTitle"), { description: t("signIn.toastBody", { role: tr(user.role) }) })
    router.push(safeNext(next, homeFor(user.role)))
  }

  return (
    <div className="flex flex-col gap-6">
      <AuthHeading title={t("signIn.title")} description={t("signIn.description")} className="max-md:-order-2" />

      <DemoHint kind="roles" />
      <FormError message={error} />

      <form noValidate onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
        <Controller
          control={control}
          name="identifier"
          render={({ field, fieldState }) => (
            <Field data-invalid={fieldState.invalid}>
              <FieldLabel htmlFor="signin-identifier">{t("fields.identifier")}</FieldLabel>
              <Input
                {...field}
                id="signin-identifier"
                autoComplete="username"
                inputMode="email"
                enterKeyHint="next"
                aria-invalid={fieldState.invalid}
                placeholder={t("fields.identifierPlaceholder")}
                className="h-10 max-md:h-12"
              />
              <FieldError>{v(fieldState.error?.message)}</FieldError>
            </Field>
          )}
        />
        <Controller
          control={control}
          name="password"
          render={({ field, fieldState }) => (
            <Field data-invalid={fieldState.invalid}>
              <div className="flex items-center justify-between">
                <FieldLabel htmlFor="signin-password">{t("fields.password")}</FieldLabel>
                <Link
                  href="/forgot-password"
                  className="text-xs text-primary underline-offset-4 hover:underline max-md:-my-3 max-md:inline-flex max-md:min-h-11 max-md:items-center max-md:text-sm"
                >
                  {t("signIn.forgot")}
                </Link>
              </div>
              <PasswordInput
                {...field}
                id="signin-password"
                autoComplete="current-password"
                enterKeyHint="go"
                aria-invalid={fieldState.invalid}
                className="h-10 max-md:h-12"
              />
              <FieldError>{v(fieldState.error?.message)}</FieldError>
            </Field>
          )}
        />
        <Controller
          control={control}
          name="remember"
          render={({ field }) => (
            <Field orientation="horizontal" className="max-md:min-h-11 max-md:items-center">
              <Checkbox
                id="signin-remember"
                checked={field.value}
                onCheckedChange={(c) => field.onChange(c === true)}
              />
              <FieldLabel htmlFor="signin-remember" className="font-normal">
                {t("signIn.remember")}
              </FieldLabel>
            </Field>
          )}
        />
        <Button type="submit" size="lg" className="h-10 max-md:h-12" disabled={formState.isSubmitting}>
          {formState.isSubmitting && <Spinner />}
          {formState.isSubmitting ? t("signIn.submitting") : t("signIn.submit")}
        </Button>
      </form>

      <SocialButtons disabled={formState.isSubmitting} next={next} className="max-md:-order-1" />

      <p className="text-center text-sm text-muted-foreground">
        {t("signIn.newHere")}{" "}
        <Link
          href={next ? `/sign-up?next=${encodeURIComponent(next)}` : "/sign-up"}
          className="font-medium text-primary underline underline-offset-4 max-md:inline-flex max-md:min-h-11 max-md:items-center"
        >
          {t("signIn.createAccount")}
        </Link>
      </p>
    </div>
  )
}
