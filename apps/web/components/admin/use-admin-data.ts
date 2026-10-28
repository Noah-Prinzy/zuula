"use client"

import * as React from "react"
import { useTranslations } from "next-intl"
import { toast } from "sonner"

import { useApiErrorMessage } from "@/hooks/use-api-error-message"
import { adminApiLive } from "@/lib/admin-api"

/**
 * One admin screen's data: `load()` from the API when it's live, `demo` (lib/mock/admin.ts)
 * in demo builds. `data` is null until the first load finishes, then keeps the last result
 * while a new one loads (a filter or page change); a failed load shows a toast. `reload()`
 * fetches again, e.g. after a change. `deps` are the load's own inputs (filters, page).
 */
export function useAdminData<T>(load: () => Promise<T>, demo: T, deps: React.DependencyList) {
  const live = adminApiLive()
  const [data, setData] = React.useState<T | null>(live ? null : demo)
  const [attempt, setAttempt] = React.useState(0)
  const t = useTranslations("Admin")
  const errorMessage = useApiErrorMessage()

  React.useEffect(() => {
    if (!live) return
    let cancelled = false
    load().then(
      (result) => {
        if (!cancelled) setData(result)
      },
      (e) => {
        if (!cancelled) toast.error(t("loadFailed"), { description: errorMessage(e) })
      }
    )
    return () => {
      cancelled = true
    }
    // Only the caller's load inputs re-run this: `load`, `t` and `errorMessage` are fresh
    // functions on every render, and depending on them would refetch in a loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, attempt, ...deps])

  return { live, data, reload: () => setAttempt((a) => a + 1), setData }
}
