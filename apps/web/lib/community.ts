import type { Role } from "@/lib/roles"
import type { CommunityRating, RaterRole, RatingCounts } from "@/lib/types/fact-check"

// §9.1 rating weights. Admins rate as standard users (the spec gives them no weight).
export const RATING_WEIGHTS: Record<RaterRole, number> = {
  public: 1,
  journalist: 2,
  expert: 5,
}

export function raterRole(role: Role): RaterRole {
  return role === "admin" ? "public" : role
}

// §9.2 escalation thresholds. Admin-configurable later (FR-ADMIN-06).
export const CCS_THRESHOLDS = {
  verified: { minScore: 90 },
  questioned: { minScore: 40, maxScore: 69, minRatings: 50 },
  escalated: { maxScore: 39, minRatings: 100 },
  suspended: { maxScore: 19, minRatings: 200 },
} as const

export type CommunityStatus = "verified" | "standard" | "questioned" | "escalated" | "suspended"

export type CommunityScore = {
  /** Weighted Community Confidence Score, 0–100, or null with no ratings. */
  ccs: number | null
  weightedAccurate: number
  weightedInaccurate: number
  /** Raw number of people who rated. */
  accurateCount: number
  inaccurateCount: number
  total: number
  status: CommunityStatus
}

function sum(c: RatingCounts) {
  return c.public + c.journalist + c.expert
}

function weighted(c: RatingCounts) {
  return (Object.keys(RATING_WEIGHTS) as RaterRole[]).reduce(
    (acc, r) => acc + c[r] * RATING_WEIGHTS[r],
    0
  )
}

// FR-RATE-03 / §9.1: CCS = weighted likes / (weighted likes + weighted dislikes) × 100.
export function communityScore(
  rating: Pick<CommunityRating, "accurate" | "inaccurate" | "score">
): CommunityScore {
  if (rating.score) return rating.score
  const wa = weighted(rating.accurate)
  const wi = weighted(rating.inaccurate)
  const accurateCount = sum(rating.accurate)
  const inaccurateCount = sum(rating.inaccurate)
  const total = accurateCount + inaccurateCount
  const ccs = wa + wi > 0 ? Math.round((wa / (wa + wi)) * 100) : null

  return {
    ccs,
    weightedAccurate: wa,
    weightedInaccurate: wi,
    accurateCount,
    inaccurateCount,
    total,
    status: statusFor(ccs, total),
  }
}

export function statusFor(ccs: number | null, total: number): CommunityStatus {
  if (ccs === null) return "standard"
  const t = CCS_THRESHOLDS
  if (ccs <= t.suspended.maxScore && total > t.suspended.minRatings) return "suspended"
  if (ccs <= t.escalated.maxScore && total > t.escalated.minRatings) return "escalated"
  if (ccs >= t.questioned.minScore && ccs <= t.questioned.maxScore && total > t.questioned.minRatings)
    return "questioned"
  if (ccs >= t.verified.minScore) return "verified"
  return "standard"
}

// Applies one person's vote change to the counts (used for optimistic UI).
export function applyVote(
  rating: Pick<CommunityRating, "accurate" | "inaccurate">,
  role: RaterRole,
  from: "accurate" | "inaccurate" | null,
  to: "accurate" | "inaccurate" | null
) {
  const next = {
    accurate: { ...rating.accurate },
    inaccurate: { ...rating.inaccurate },
  }
  if (from) next[from][role] = Math.max(0, next[from][role] - 1)
  if (to) next[to][role] += 1
  return next
}
