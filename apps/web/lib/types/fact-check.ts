// Domain types for fact-check reports. These become the API contract in Phase 2
// (moved to packages/shared and generated from OpenAPI).

// FR-DETECT-01: the five verdict categories.
export const VERDICTS = [
  "authentic",
  "likely-false",
  "false",
  "ai-generated",
  "unverifiable",
] as const

export type Verdict = (typeof VERDICTS)[number]

export type ContentType = "text" | "url" | "image" | "audio" | "video"

// FR-DETECT-05 / FR-EXPLAIN-04: a problematic span inside the submitted text.
export type ClaimAssessment = "false" | "misleading" | "unsupported" | "out-of-context" | "supported"

export type FlaggedClaim = {
  id: string
  /** Character offsets into the submitted text (end exclusive). */
  start: number
  end: number
  assessment: ClaimAssessment
  reason: string
  /** Citation ids that back up the assessment. */
  citationIds: string[]
}

// FR-EXPLAIN-02 / 03
export type CitationStance = "supports" | "contradicts" | "context"

export type Citation = {
  id: string
  sourceName: string
  title: string
  url: string
  publishedAt: string // ISO date
  stance: CitationStance
  trusted: boolean
  excerpt?: string
}

// FR-EXPLAIN-06: why content was flagged as AI-generated / manipulated.
export type AISignal = {
  id: string
  label: string
  description: string
  /** 0–1, higher = more likely AI/manipulated. */
  score: number
  threshold: number
  method: string
}

// FR-EXPLAIN-08
export type ExpertAnnotation = {
  id: string
  author: string
  role: string
  createdAt: string
  body: string
}

// FR-REVIEW-02–04
export type HumanReview = {
  outcome: "confirmed" | "overridden"
  reviewer: string
  reviewedAt: string
  previousVerdict?: Verdict
  justification: string
}

// FR-RATE: raw rating counts by rater role (weights applied in lib/community.ts).
export type RaterRole = "public" | "journalist" | "expert"

export type RatingCounts = Record<RaterRole, number>

export type RatingComment = {
  id: string
  author: string
  role: RaterRole
  vote: "accurate" | "inaccurate"
  body: string
  createdAt: string
}

// Mirrors lib/community.ts's CommunityScore (duplicated, not imported, to keep this file
// dependency-free — lib/community.ts already imports types from here).
export type PrecomputedCommunityScore = {
  ccs: number | null
  weightedAccurate: number
  weightedInaccurate: number
  accurateCount: number
  inaccurateCount: number
  total: number
  status: "verified" | "standard" | "questioned" | "escalated" | "suspended"
}

export type CommunityRating = {
  accurate: RatingCounts
  inaccurate: RatingCounts
  comments: RatingComment[]
  /** Present only for reports sourced from the real API, whose score is computed server-side
   * from per-role counts this type doesn't carry — lib/community.ts's communityScore() returns
   * this as-is instead of recomputing it from `accurate`/`inaccurate` when it's set. */
  score?: PrecomputedCommunityScore
}

export type FactCheckReport = {
  id: string
  trackingId: string
  title: string
  contentType: ContentType
  language: string
  submittedText: string
  sourceUrl?: string
  verdict: Verdict
  /** FR-DETECT-02: 0–100. */
  confidence: number
  summary: string
  /** FR-EXPLAIN-07 */
  whatIsFalse: string[]
  whatIsTrue: string[]
  claims: FlaggedClaim[]
  citations: Citation[]
  aiSignals: AISignal[]
  annotations: ExpertAnnotation[]
  humanReview?: HumanReview
  community: CommunityRating
  category: string
  checkedAt: string
  processingSeconds: number
}
