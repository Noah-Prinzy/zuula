"use client"

import type * as React from "react"

import { useLiveData } from "@/hooks/use-live-data"
import { adminApiLive } from "@/lib/admin-api"

/** An admin screen's data: the API when it's live, lib/mock/admin.ts in demo builds. */
export function useAdminData<T>(load: () => Promise<T>, demo: T, deps: React.DependencyList) {
  return useLiveData(adminApiLive(), load, demo, deps)
}
