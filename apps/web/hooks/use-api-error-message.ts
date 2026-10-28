import * as React from "react"
import { useTranslations } from "next-intl"

import { ApiError } from "@/lib/api"

// Text for a failed apps/api call. The API's own messages are written for end users
// ("That code didn't work…"), so they're shown as is (English only for now); failures before
// any response get a translated message instead. Stable across renders, so it's safe in an
// effect's dependencies.
export function useApiErrorMessage() {
  const t = useTranslations("Auth.errors")
  return React.useCallback(
    (error: unknown) => {
      if (error instanceof ApiError) {
        if (error.code === "unconfigured") return t("unconfigured")
        if (error.code !== "network") return error.message
      }
      return t("network")
    },
    [t]
  )
}
