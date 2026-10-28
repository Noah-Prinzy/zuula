import type { components, operations } from "@zuula/shared"

import { ApiError, apiBaseUrl, authMode, request, type JsonBody } from "@/lib/api"
import { accessToken } from "@/lib/supabase-auth"

// Real apps/api client for the signed-in user's own account (FR-AUTH, FR-ACCOUNT): activity,
// notifications, API keys, alert settings, devices, password, two-factor, data export and
// erasure, and accreditation. Screens check accountApiLive() and keep lib/mock/account.ts in
// demo builds; the mock types mirror these schemas field for field.

type Schemas = components["schemas"]
type Ok<Op extends keyof operations> = operations[Op] extends {
  responses: { 200: { content: { "application/json": infer R } } }
}
  ? R
  : never

export type AppNotification = Schemas["AppNotification"]
export type ActivitySubmission = Schemas["ActivitySubmission"]
export type ActivityRating = Schemas["ActivityRating"]
export type DeviceSession = Schemas["DeviceSession"]
export type ApiKey = Schemas["ApiKey"]
export type AlertSettings = Schemas["AlertSettings"]
export type CreatedApiKey = operations["createApiKey"]["responses"][201]["content"]["application/json"]
export type ApiUsage = Ok<"getApiUsage">
export type Verification = Ok<"getVerification">

type Paged<T> = { data: T[]; page: number; perPage: number; total: number }

export function accountApiLive(): boolean {
  return authMode() !== "demo"
}

export const accountApi = {
  updateMe: (body: JsonBody<"updateMe">) => request<Schemas["UserProfile"]>("/api/v1/me", { method: "PATCH", body }),
  deleteMe: () => request<void>("/api/v1/me", { method: "DELETE" }),
  changePassword: (body: JsonBody<"changePassword">) => request<void>("/api/v1/me/password", { method: "POST", body }),
  setTwoFactor: (body: JsonBody<"setTwoFactor">) => request<unknown>("/api/v1/me/two-factor", { method: "POST", body }),
  sessions: () => request<DeviceSession[]>("/api/v1/me/sessions"),
  revokeSession: (id: string) => request<void>(`/api/v1/me/sessions/${encodeURIComponent(id)}`, { method: "DELETE" }),
  exportData: () => request<unknown>("/api/v1/me/data-export"),

  submissions: () => request<Paged<ActivitySubmission>>("/api/v1/me/submissions?perPage=100"),
  ratings: () => request<Paged<ActivityRating>>("/api/v1/me/ratings?perPage=100"),

  notifications: () => request<Paged<AppNotification>>("/api/v1/notifications?perPage=100"),
  markRead: (id: string) => request<void>(`/api/v1/notifications/${encodeURIComponent(id)}/read`, { method: "POST" }),
  markAllRead: () => request<void>("/api/v1/notifications/read-all", { method: "POST" }),

  apiKeys: () => request<ApiKey[]>("/api/v1/me/api-keys"),
  createApiKey: (body: JsonBody<"createApiKey">) => request<CreatedApiKey>("/api/v1/me/api-keys", { method: "POST", body }),
  revokeApiKey: (id: string) => request<void>(`/api/v1/me/api-keys/${encodeURIComponent(id)}`, { method: "DELETE" }),
  apiUsage: () => request<ApiUsage>("/api/v1/me/api-usage"),

  alertSettings: () => request<AlertSettings>("/api/v1/me/alert-settings"),
  updateAlertSettings: (body: AlertSettings) =>
    request<AlertSettings>("/api/v1/me/alert-settings", { method: "PATCH", body }),

  verification: () => request<Verification>("/api/v1/me/verification"),
  /** POST /me/verification is multipart (the documents), so it bypasses request()'s JSON body. */
  async applyForVerification(form: FormData): Promise<void> {
    const base = apiBaseUrl()
    if (base === null) throw new ApiError(0, "unconfigured", "NEXT_PUBLIC_API_URL is not set.")
    const token = authMode() === "supabase" ? await accessToken() : null
    let res: Response
    try {
      res = await fetch(`${base}/api/v1/me/verification`, {
        method: "POST",
        credentials: "include",
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        body: form,
      })
    } catch {
      throw new ApiError(0, "network", "Couldn't reach the Zuula API.")
    }
    if (res.ok) return
    const error = ((await res.json().catch(() => undefined)) as Partial<Schemas["ErrorEnvelope"]> | undefined)?.error
    throw new ApiError(res.status, error?.code ?? "server_error", error?.message ?? `Request failed (${res.status}).`)
  },
}
