"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import { useTranslations } from "next-intl"

import { useSession } from "@/components/providers/session-provider"
import { Spinner } from "@/components/ui/spinner"
import { authApi } from "@/lib/api"
import { homeFor, safeNext } from "@/lib/auth"

// Where Supabase sends the browser back after Google/Facebook sign-in or an email link
// (NEXT_PUBLIC_AUTH_MODE=supabase). lib/supabase.ts's client reads the session from the URL as
// it loads; this asks the API for the Zuula account behind it and goes on to `next`, or to the
// role's home. Failures land on /sign-in?error=oauth, the same as the API's own OAuth callback.
export function AuthCallback({
  next,
  error,
}: {
  next?: string
  error?: string
}) {
  const router = useRouter()
  const { setAccount } = useSession()
  const t = useTranslations("Common")
  const started = React.useRef(false)

  React.useEffect(() => {
    if (started.current) return
    started.current = true
    const failed = () => router.replace("/sign-in?error=oauth")
    if (error) return failed()
    authApi.me().then((user) => {
      if (!user) return failed()
      setAccount(user)
      router.replace(safeNext(next, homeFor(user.role)))
    }, failed)
  }, [error, next, router, setAccount])

  return (
    <div
      role="status"
      className="flex flex-1 items-center justify-center gap-2 text-sm text-muted-foreground"
    >
      <Spinner aria-hidden />
      {t("loading")}
    </div>
  )
}
