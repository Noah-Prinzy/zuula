"use client"

import * as React from "react"

import { useSession } from "@/components/providers/session-provider"
import { accountApi, accountApiLive } from "@/lib/account-api"
import { SAMPLE_NOTIFICATIONS, type AppNotification } from "@/lib/mock/account"

// Shared by the header bell and the Notifications page so "read" state stays in sync. Live,
// the signed-in user's notifications come from the API (GET /notifications) and reading them is
// saved there; the API has no "mark unread" or delete, so those only change this page view.
// Signed out there are none. Demo builds use the samples.

const INITIAL: AppNotification[] = accountApiLive() ? [] : SAMPLE_NOTIFICATIONS
let items: AppNotification[] = INITIAL
// Whose notifications `items` holds: an account's address, "" when signed out, null before the
// first load.
let loadedFor: string | null = null
const listeners = new Set<() => void>()

function set(next: AppNotification[]) {
  items = next
  listeners.forEach((l) => l())
}

function subscribe(l: () => void) {
  listeners.add(l)
  return () => listeners.delete(l)
}

export function markRead(id: string) {
  set(items.map((n) => (n.id === id ? { ...n, read: true } : n)))
  if (accountApiLive()) accountApi.markRead(id).catch(() => undefined)
}

export function markUnread(id: string) {
  set(items.map((n) => (n.id === id ? { ...n, read: false } : n)))
}

export function markAllRead() {
  set(items.map((n) => ({ ...n, read: true })))
  if (accountApiLive()) accountApi.markAllRead().catch(() => undefined)
}

export function removeNotification(id: string) {
  set(items.filter((n) => n.id !== id))
}

export function useNotifications() {
  const { user, source } = useSession()
  const account = source === "account" ? (user?.email ?? "") : ""

  React.useEffect(() => {
    if (!accountApiLive() || account === loadedFor) return
    loadedFor = account
    if (!account) return set([])
    accountApi.notifications().then(
      (page) => {
        if (loadedFor === account) set(page.data)
      },
      () => undefined
    )
  }, [account])

  const list = React.useSyncExternalStore(subscribe, () => items, () => INITIAL)
  return { items: list, unread: list.filter((n) => !n.read).length }
}
