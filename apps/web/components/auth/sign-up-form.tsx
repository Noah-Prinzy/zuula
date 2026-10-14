"use client"

import * as React from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { zodResolver } from "@hookform/resolvers/zod"
import { useTranslations } from "next-intl"
import { Controller, useForm, useWatch } from "react-hook-form"
import type { z } from "zod"

import { AuthHeading } from "@/components/auth/auth-heading"
import { FormError } from "@/components/auth/form-error"
import { PasswordInput } from "@/components/auth/password-input"
import { PasswordStrength } from "@/components/auth/password-strength"
import { SocialButtons } from "@/components/auth/social-buttons"
import { startNavigationProgress } from "@/components/shell/route-progress"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { useIsMobile } from "@/hooks/use-mobile"
import { Spinner } from "@/components/ui/spinner"
import { useApiErrorMessage } from "@/hooks/use-api-error-message"
import { useValidationMessage } from "@/hooks/use-validation-message"
import { ApiError, authApi } from "@/lib/api"
import { safeNext, setPendingAuth, signUpSchema } from "@/lib/auth"

type Values = z.infer<typeof signUpSchema>

export function SignUpForm({ next }: { next?: string }) {
  const router = useRouter()
  const t = useTranslations("Auth")
  const v = useValidationMessage()
  const apiMessage = useApiErrorMessage()
  const [error, setError] = React.useState<string | null>(null)
  const form = useForm<Values>({
    resolver: zodResolver(signUpSchema),
    defaultValues: { name: "", identifier: "", password: "", confirm: "", consent: false },
  })
  const { control, handleSubmit, formState, setError: setFieldError } = form
  const password = useWatch({ control, name: "password" })
  // Phones skip "Confirm password": retyping it on a phone keyboard is where sign-ups are
  // abandoned, and the show-password toggle lets people check what they typed instead.
  const isMobile = useIsMobile()
  React.useEffect(() => {
    if (isMobile) form.setValue("confirm", password)
  }, [isMobile, password, form])

  async function onSubmit(values: Values) {
    setError(null)
    const identifier = values.identifier.trim()
    let accepted
    try {
      // 202: the API holds the sign-up and sends a code; the account exists once it's verified.
      accepted = await authApi.signUp({
        name: values.name.trim(),
        identifier,
        password: values.password,
        consent: values.consent,
      })
    } catch (e) {
      // 409: that email or phone number already has an account.
      if (e instanceof ApiError && e.code === "conflict") setFieldError("identifier", { message: e.message })
      else setError(apiMessage(e))
      return
    }
    setPendingAuth({
      identifier,
      name: values.name.trim(),
      next: safeNext(next, "") || undefined,
      maskedIdentifier: accepted?.maskedIdentifier,
    })
    startNavigationProgress()
    router.push("/sign-up/verify")
  }

  return (
    <div className="flex flex-col gap-6">
      <AuthHeading title={t("signUp.title")} description={t("signUp.description")} className="max-md:-order-2" />

      <FormError message={error} />

      <form noValidate onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
        <Controller
          control={control}
          name="name"
          render={({ field, fieldState }) => (
            <Field data-invalid={fieldState.invalid}>
              <FieldLabel htmlFor="signup-name">{t("fields.fullName")}</FieldLabel>
              <Input
                {...field}
                id="signup-name"
                autoComplete="name"
                autoCapitalize="words"
                enterKeyHint="next"
                aria-invalid={fieldState.invalid}
                className="h-10 max-md:h-12"
              />
              <FieldError>{v(fieldState.error?.message)}</FieldError>
            </Field>
          )}
        />
        <Controller
          control={control}
          name="identifier"
          render={({ field, fieldState }) => (
            <Field data-invalid={fieldState.invalid}>
              <FieldLabel htmlFor="signup-identifier">{t("fields.identifier")}</FieldLabel>
              <Input
                {...field}
                id="signup-identifier"
                autoComplete="username"
                inputMode="email"
                enterKeyHint="next"
                aria-invalid={fieldState.invalid}
                placeholder={t("fields.identifierPlaceholder")}
                className="h-10 max-md:h-12"
              />
              <FieldDescription>{t("signUp.identifierHint")}</FieldDescription>
              <FieldError>{v(fieldState.error?.message)}</FieldError>
            </Field>
          )}
        />
        <Controller
          control={control}
          name="password"
          render={({ field, fieldState }) => (
            <Field data-invalid={fieldState.invalid}>
              <FieldLabel htmlFor="signup-password">{t("fields.password")}</FieldLabel>
              <PasswordInput
                {...field}
                id="signup-password"
                autoComplete="new-password"
                enterKeyHint={isMobile ? "done" : "next"}
                aria-invalid={fieldState.invalid}
                aria-describedby={password ? "signup-password-strength" : undefined}
                className="h-10 max-md:h-12"
              />
              {/* The meter and checklist appear once typing starts, not as four ✕ rows up front. */}
              {password && <PasswordStrength id="signup-password-strength" password={password} />}
              <FieldError>{v(fieldState.error?.message)}</FieldError>
            </Field>
          )}
        />
        {!isMobile && <Controller
          control={control}
          name="confirm"
          render={({ field, fieldState }) => (
            <Field data-invalid={fieldState.invalid}>
              <FieldLabel htmlFor="signup-confirm">{t("fields.confirmPassword")}</FieldLabel>
              <PasswordInput
                {...field}
                id="signup-confirm"
                autoComplete="new-password"
                aria-invalid={fieldState.invalid}
                className="h-10 max-md:h-12"
              />
              <FieldError>{v(fieldState.error?.message)}</FieldError>
            </Field>
          )}
        />}
        <Controller
          control={control}
          name="consent"
          render={({ field, fieldState }) => (
            <Field data-invalid={fieldState.invalid}>
              <div className="flex items-start gap-2 max-md:min-h-11 max-md:py-1">
                <Checkbox
                  id="signup-consent"
                  checked={field.value}
                  onCheckedChange={(c) => field.onChange(c === true)}
                  aria-invalid={fieldState.invalid}
                  className="mt-0.5"
                />
                <FieldLabel htmlFor="signup-consent" className="block font-normal leading-snug">
                  {t.rich("signUp.consent", {
                    terms: (chunks) => (
                      <Link href="/legal/terms" className="text-primary underline underline-offset-2">
                        {chunks}
                      </Link>
                    ),
                    privacy: (chunks) => (
                      <Link href="/legal/privacy" className="text-primary underline underline-offset-2">
                        {chunks}
                      </Link>
                    ),
                  })}
                </FieldLabel>
              </div>
              <FieldError>{v(fieldState.error?.message)}</FieldError>
            </Field>
          )}
        />
        <Button type="submit" size="lg" className="h-10 max-md:h-12" disabled={formState.isSubmitting}>
          {formState.isSubmitting && <Spinner />}
          {formState.isSubmitting ? t("signUp.submitting") : t("signUp.submit")}
        </Button>
      </form>

      <SocialButtons disabled={formState.isSubmitting} next={next} className="max-md:-order-1" />

      <p className="text-center text-sm text-muted-foreground">
        {t("signUp.haveAccount")}{" "}
        <Link
          href={next ? `/sign-in?next=${encodeURIComponent(next)}` : "/sign-in"}
          className="font-medium text-primary underline underline-offset-4 max-md:inline-flex max-md:min-h-11 max-md:items-center"
        >
          {t("signUp.signIn")}
        </Link>
      </p>
    </div>
  )
}
