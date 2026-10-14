"use client"

import { RiFacebookFill, RiGoogleFill } from "@remixicon/react"
import { useTranslations } from "next-intl"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { apiBaseUrl, authMode } from "@/lib/api"
import { safeNext } from "@/lib/auth"
import { cn } from "@/lib/utils"

type Provider = "google" | "facebook"

// FR-AUTH-01: social login. The API runs the OAuth round trip: /start sends the browser to the
// provider, and its callback sets the session cookie and comes back to the web app (`next`, or
// /sign-in/two-factor?challenge=… when a second factor is due, or /sign-in?error=… on failure).
// A full-page navigation, not fetch: the provider's pages can't load in the background.
// In demo mode (no API) there is nothing to sign in with, so the buttons only explain that.
// Phones put these first (the forms order them with max-md:-order-1): one tap beats typing an
// address and password on a phone keyboard. The divider then sits below them and leads into
// the form, instead of above them after it.
export function SocialButtons({
  disabled,
  next,
  className,
}: {
  disabled?: boolean
  next?: string
  className?: string
}) {
  const t = useTranslations("Auth.social")

  function start(provider: Provider, label: string) {
    const base = apiBaseUrl()
    if (authMode() === "demo" || base === null) {
      toast.info(t("notConnected", { provider: label }), { description: t("notConnectedBody") })
      return
    }
    const query = new URLSearchParams({ next: safeNext(next, "/") })
    window.location.assign(`${base}/api/v1/auth/oauth/${provider}/start?${query}`)
  }

  return (
    <div className={cn("flex flex-col gap-3", className)}>
      <div className="flex items-center gap-3 text-xs text-muted-foreground max-md:order-last">
        <span className="h-px flex-1 bg-border" />
        <span className="max-md:hidden">{t("divider")}</span>
        <span className="md:hidden">{t("dividerEmail")}</span>
        <span className="h-px flex-1 bg-border" />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Button type="button" variant="outline" size="lg" disabled={disabled} onClick={() => start("google", "Google")} className="max-md:h-12">
          <RiGoogleFill aria-hidden /> Google
        </Button>
        <Button type="button" variant="outline" size="lg" disabled={disabled} onClick={() => start("facebook", "Facebook")} className="max-md:h-12">
          <RiFacebookFill aria-hidden /> Facebook
        </Button>
      </div>
    </div>
  )
}
