// Real apps/api client for community ratings (FR-RATE-01…07): voting, retracting, rating
// comments and reporting an issue with a verdict. Reuses lib/api.ts's request()/JsonBody/
// JsonResponse conventions (credentials included, apiBaseUrl()-gated) rather than lib/mock —
// unlike lib/fact-checks-api.ts's read-only GETs, every call here is a signed-in mutation, so
// there's no sensible silent fallback: callers check ratingsApiConfigured() themselves (mirrors
// authMode() === "demo") and keep today's local-only behavior when it's false.

import { ApiError, apiBaseUrl, request, type JsonBody } from "@/lib/api"
import type { CommunityScore } from "@/lib/community"
import type { RatingComment } from "@/lib/types/fact-check"

export { ApiError }

export function ratingsApiConfigured(): boolean {
  return apiBaseUrl() !== null
}

type Vote = "accurate" | "inaccurate"

/** POST .../ratings (FR-RATE-01, weighted by role in §9.1). */
export function rate(reportId: string, vote: Vote): Promise<CommunityScore> {
  const body: JsonBody<"rateFactCheck"> = { vote }
  return request<CommunityScore>(`/api/v1/fact-checks/${reportId}/ratings`, {
    method: "POST",
    body,
  })
}

/** DELETE .../ratings — retract my vote (FR-RATE-04, 09). */
export function retractRating(reportId: string): Promise<CommunityScore> {
  return request<CommunityScore>(`/api/v1/fact-checks/${reportId}/ratings`, { method: "DELETE" })
}

/** POST .../comments — "rate with a comment": the comment's vote is also the user's rating,
 * and each call adds a new public comment (there's no edit; see rating-panel.tsx). */
export function addComment(reportId: string, vote: Vote, body: string): Promise<RatingComment> {
  const payload: JsonBody<"addComment"> = { vote, body }
  return request<RatingComment>(`/api/v1/fact-checks/${reportId}/comments`, {
    method: "POST",
    body: payload,
  })
}

type CommentsPage = { data: RatingComment[]; page: number; perPage: number; total: number }

/** GET .../comments, newest first. */
export function listComments(reportId: string, page = 1): Promise<CommentsPage> {
  return request<CommentsPage>(`/api/v1/fact-checks/${reportId}/comments?page=${page}`)
}

/** POST .../report-issue (FR-RATE-07) — flags the verdict, or one comment when `commentId` is
 * given, for moderator attention. */
export function reportIssue(
  reportId: string,
  reason: string,
  commentId?: string
): Promise<void> {
  const body: JsonBody<"reportFactCheckIssue"> = commentId ? { reason, commentId } : { reason }
  return request<void>(`/api/v1/fact-checks/${reportId}/report-issue`, { method: "POST", body })
}
