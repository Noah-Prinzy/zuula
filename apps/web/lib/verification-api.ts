// Real apps/api client for accreditation review (FR-AUTH-02): the admin queue of Verified
// Journalist / Expert Reviewer applications, one application with its documents, and the
// approve/reject decision. Reuses lib/api.ts's request()/JsonBody conventions, same as
// lib/review-api.ts — every call needs a signed-in Admin, so callers check
// verificationApiConfigured() and keep lib/mock/admin.ts's sample applications when it's false.

import type { components } from "@zuula/shared"

import { apiBaseUrl, authMode, request, type JsonBody } from "@/lib/api"

type Schemas = components["schemas"]

export type AccreditationApplication = Schemas["AccreditationApplication"]
export type AccreditationApplicationDetail = Schemas["AccreditationApplicationDetail"]
export type AccreditationDocument = AccreditationApplicationDetail["documents"][number]
export type AccreditationStatus = AccreditationApplication["status"]
export type AccreditationRole = Schemas["AccreditationRole"]
export type VerificationDecision = JsonBody<"decideVerificationApplication">

type Paged<T> = { data: T[]; page: number; perPage: number; total: number }

/** Admin calls need a real API session, so the demo sign-in (lib/demo-auth.ts) gets samples. */
export function verificationApiConfigured(): boolean {
  return authMode() === "api"
}

/** GET /admin/verifications — pending oldest first, then decided ones, newest decision first. */
export function listApplications(
  params: { status?: AccreditationStatus; page?: number; perPage?: number } = {}
): Promise<Paged<AccreditationApplication>> {
  const qs = new URLSearchParams()
  if (params.status) qs.set("status", params.status)
  if (params.page) qs.set("page", String(params.page))
  if (params.perPage) qs.set("perPage", String(params.perPage))
  const suffix = qs.size ? `?${qs}` : ""
  return request<Paged<AccreditationApplication>>(`/api/v1/admin/verifications${suffix}`)
}

/** GET /admin/verifications/{id} — the application, its applicant and signed document links. */
export function getApplication(id: string): Promise<AccreditationApplicationDetail> {
  return request<AccreditationApplicationDetail>(`/api/v1/admin/verifications/${encodeURIComponent(id)}`)
}

/** POST /admin/verifications/{id}/decision — approve (grants the requested role) or reject
 * with a note the applicant sees. */
export function decideApplication(
  id: string,
  body: VerificationDecision
): Promise<AccreditationApplicationDetail> {
  return request<AccreditationApplicationDetail>(
    `/api/v1/admin/verifications/${encodeURIComponent(id)}/decision`,
    { method: "POST", body }
  )
}

/** A document's signed path is relative to the API; this is the address to open. The link
 * carries its own signature (no cookie needed) and expires after 10 minutes. */
export function documentHref(doc: Pick<AccreditationDocument, "url">): string {
  return `${apiBaseUrl() ?? ""}${doc.url}`
}

/** Whether a document link has expired (refetch the application for fresh ones). */
export function documentExpired(doc: Pick<AccreditationDocument, "expiresAt">, now: Date = new Date()): boolean {
  return new Date(doc.expiresAt).getTime() <= now.getTime()
}
