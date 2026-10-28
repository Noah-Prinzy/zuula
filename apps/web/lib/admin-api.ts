import type { components, operations } from "@zuula/shared"

import { authMode, request, type JsonBody } from "@/lib/api"

// Real apps/api client for the admin console (FR-ADMIN-01…07): every call needs a signed-in
// Admin. Screens check adminApiLive() and keep lib/mock/admin.ts's sample data in demo builds
// (no API), the same split as lib/verification-api.ts and lib/submissions-api.ts. The mock
// types mirror these schemas field for field, so a screen renders either source unchanged.

type Schemas = components["schemas"]
type Ok<Op extends keyof operations> = operations[Op] extends {
  responses: { 200: { content: { "application/json": infer R } } }
}
  ? R
  : never
type Query<Op extends keyof operations> = operations[Op] extends {
  parameters: { query?: infer Q }
}
  ? NonNullable<Q>
  : never

export type AdminOverview = Ok<"getAdminOverview">
export type AdminUser = Schemas["AdminUser"]
export type ContentReport = Schemas["ContentReport"]
export type ManipulationSignal = Schemas["ManipulationSignal"]
export type TrustedSource = Schemas["TrustedSource"]
export type Broadcast = Schemas["Broadcast"]
export type MonthlyReport = Schemas["MonthlyReport"]
export type AuditEntry = Schemas["AuditEntry"]
export type PlatformSettings = Schemas["PlatformSettings"]

export type Paged<T> = { data: T[]; page: number; perPage: number; total: number }
/** Every list endpoint also takes `perPage` (1–100, default 20; app/core/pagination.py). */
type PageSize = { perPage?: number }

export function adminApiLive(): boolean {
  return authMode() !== "demo"
}

function qs(params: object): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value))
  }
  return search.size ? `?${search}` : ""
}

const path = (id: string) => encodeURIComponent(id)

export const adminApi = {
  overview: () => request<AdminOverview>("/api/v1/admin/overview"),

  users: (params: Query<"listAdminUsers"> & PageSize = {}) =>
    request<Paged<AdminUser>>(`/api/v1/admin/users${qs(params)}`),
  updateUser: (id: string, body: JsonBody<"updateAdminUser">) =>
    request<AdminUser>(`/api/v1/admin/users/${path(id)}`, { method: "PATCH", body }),

  contentReports: (params: Query<"listContentReports"> & PageSize = {}) =>
    request<Paged<ContentReport>>(`/api/v1/admin/moderation/reports${qs(params)}`),
  resolveContentReport: (id: string, body: JsonBody<"resolveContentReport">) =>
    request<void>(`/api/v1/admin/moderation/reports/${path(id)}/resolve`, { method: "POST", body }),
  signals: () => request<ManipulationSignal[]>("/api/v1/admin/moderation/signals"),

  sources: (params: Query<"listSources"> & PageSize = {}) =>
    request<Paged<TrustedSource>>(`/api/v1/admin/sources${qs(params)}`),
  addSource: (body: JsonBody<"addSource">) =>
    request<TrustedSource>("/api/v1/admin/sources", { method: "POST", body }),
  updateSource: (id: string, body: JsonBody<"updateSource">) =>
    request<TrustedSource>(`/api/v1/admin/sources/${path(id)}`, { method: "PATCH", body }),
  removeSource: (id: string) =>
    request<void>(`/api/v1/admin/sources/${path(id)}`, { method: "DELETE" }),

  broadcasts: () => request<Broadcast[]>("/api/v1/admin/broadcasts"),
  sendBroadcast: (body: JsonBody<"sendBroadcast">) =>
    request<Broadcast>("/api/v1/admin/broadcasts", { method: "POST", body }),

  monthlyReports: () => request<MonthlyReport[]>("/api/v1/admin/reports"),

  auditLog: (params: Query<"listAuditLog"> & PageSize = {}) =>
    request<Paged<AuditEntry>>(`/api/v1/admin/audit-log${qs(params)}`),

  settings: () => request<PlatformSettings>("/api/v1/admin/settings"),
  updateSettings: (body: JsonBody<"updatePlatformSettings">) =>
    request<PlatformSettings>("/api/v1/admin/settings", { method: "PATCH", body }),
}
