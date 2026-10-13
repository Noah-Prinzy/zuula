// Real apps/api client for expert review (FR-REVIEW-01…06): the queue, a case, assignment,
// decisions and history. Reuses lib/api.ts's request()/JsonBody conventions, same as
// lib/ratings-api.ts — every call here needs a signed-in Expert/Admin, so there's no sensible
// silent fallback; callers check reviewApiConfigured() and keep lib/mock/review.ts's sample
// data when it's false, same "demo when unconfigured" pattern as the rest of the app.

import { apiBaseUrl, request, type JsonBody } from "@/lib/api"
import type { FactCheckReport, Verdict } from "@/lib/types/fact-check"

export function reviewApiConfigured(): boolean {
  return apiBaseUrl() !== null
}

export type ReviewReason = "community-escalation" | "suspended" | "user-reports" | "low-confidence"
export type SlaState = "overdue" | "due-soon" | "on-track"

export type ReviewCase = {
  id: string
  reportId: string
  reason: ReviewReason
  flaggedAt: string
  reports?: number
  assignee: string | null
  priority: "normal" | "high"
  /** Computed server-side; absent once the case is decided (only "open" cases carry an SLA). */
  slaDueAt?: string
  slaState?: SlaState
}

export type ReviewDecision = {
  id: string
  caseId: string
  reportId: string
  title: string
  outcome: "confirmed" | "overridden"
  from: Verdict
  to: Verdict
  justification: string
  reviewer: string
  decidedAt: string
  turnaroundHours: number
}

type Paged<T> = { data: T[]; page: number; perPage: number; total: number }

// Matches app/core/rules.py's REVIEW_DUE_SOON_HOURS (12) — a case due within this window is
// "due-soon" rather than "on-track". Shared by components/review/review-badges.tsx's SlaBadge
// and anywhere else that needs the same real-time (not lib/mock/review.ts's frozen demo clock)
// SLA state for a due timestamp.
const DUE_SOON_HOURS = 12

export function hoursLeftFor(dueAt: string, now: Date = new Date()): number {
  return (new Date(dueAt).getTime() - now.getTime()) / 3_600_000
}

export function slaStateFromHours(hoursLeft: number): SlaState {
  if (hoursLeft < 0) return "overdue"
  return hoursLeft < DUE_SOON_HOURS ? "due-soon" : "on-track"
}

const REVIEW_SLA_HOURS = 48 // matches app/core/rules.py's REVIEW_SLA_HOURS

/** The SLA deadline for a case: the API's own slaDueAt when present (every open case has one),
 * or flaggedAt + 48h for sample data / the rare case missing it. */
export function dueAtFor(c: { flaggedAt: string; slaDueAt?: string }): string {
  return c.slaDueAt ?? new Date(new Date(c.flaggedAt).getTime() + REVIEW_SLA_HOURS * 3_600_000).toISOString()
}

export type ReviewOverview = {
  queueSize: number
  overdue: number
  dueSoon: number
  recentDecisions: ReviewDecision[]
}

/** GET /review/overview — SLA summary and the 5 most recent decisions (any reviewer). */
export function getOverview(): Promise<ReviewOverview> {
  return request<ReviewOverview>("/api/v1/review/overview")
}

/** GET /review/queue (FR-REVIEW-01, 06) — open cases, most urgent first. `assignee` is "me",
 * "unassigned", or a reviewer's user id. */
export function getQueue(
  params: { reason?: ReviewReason; assignee?: string; page?: number; perPage?: number } = {}
): Promise<Paged<ReviewCase>> {
  const qs = new URLSearchParams()
  if (params.reason) qs.set("reason", params.reason)
  if (params.assignee) qs.set("assignee", params.assignee)
  if (params.page) qs.set("page", String(params.page))
  if (params.perPage) qs.set("perPage", String(params.perPage))
  const suffix = qs.size ? `?${qs}` : ""
  return request<Paged<ReviewCase>>(`/api/v1/review/queue${suffix}`)
}

/** GET /review/cases/{id} (FR-REVIEW-02…05) — a case with its full report. */
export function getCase(id: string): Promise<{ case: ReviewCase; report: FactCheckReport | null }> {
  return request(`/api/v1/review/cases/${id}`)
}

/** POST /review/cases/{id}/assign — omit `assigneeId` to assign to myself. */
export function assignCase(id: string, assigneeId?: string): Promise<ReviewCase> {
  const body: JsonBody<"assignReviewCase"> = assigneeId ? { assigneeId } : {}
  return request<ReviewCase>(`/api/v1/review/cases/${id}/assign`, { method: "POST", body })
}

/** POST /review/cases/{id}/decision (FR-REVIEW-02, 03) — confirm or override the verdict. */
export function decideCase(
  id: string,
  body: JsonBody<"decideReviewCase">
): Promise<ReviewDecision> {
  return request<ReviewDecision>(`/api/v1/review/cases/${id}/decision`, { method: "POST", body })
}

/** GET /review/history (FR-REVIEW-03) — my past decisions, newest first. */
export function getHistory(page = 1): Promise<Paged<ReviewDecision>> {
  return request<Paged<ReviewDecision>>(`/api/v1/review/history?page=${page}`)
}
