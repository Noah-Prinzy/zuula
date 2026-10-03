// Real apps/api client for fact-check content (search, facets, the home feed, a full report,
// related reports). Mirrors lib/api.ts's request() conventions (apiBaseUrl(), credentials
// included, no-store) but isn't merged into it: lib/api.ts is typed around auth's JSON-body
// operations, and these are all plain GETs.
//
// Every exported fetch function throws ApiError (reused from lib/api.ts) on failure — including
// when apiBaseUrl() is null (no NEXT_PUBLIC_API_URL configured, e.g. today's production build
// with no API hosted yet). Callers (the page components) catch that and fall back to
// lib/mock/fact-checks.ts's SAMPLE_REPORTS, the same "demo when unconfigured" pattern
// lib/demo-auth.ts uses for sign-in.

import { apiBaseUrl, ApiError } from "@/lib/api"
import { facets as facetsOf } from "@/lib/library"
import type {
  CommunityRating,
  ContentType,
  FactCheckReport,
  PrecomputedCommunityScore,
  Verdict,
} from "@/lib/types/fact-check"

type ApiSummary = {
  id: string
  trackingId: string
  title: string
  contentType: ContentType
  language: string
  verdict: Verdict
  confidence: number
  summary: string
  category: string
  checkedAt: string
  score?: PrecomputedCommunityScore
}

type ApiReport = Omit<FactCheckReport, "community"> & {
  community: Omit<CommunityRating, "score"> & { score: PrecomputedCommunityScore }
}

type HomeFeedResponse = {
  recent: ApiSummary[]
  debated: ApiSummary[]
  trending: { category: string; count: number }[]
  leaderboard: { report: ApiSummary; score: PrecomputedCommunityScore }[]
}

type SearchResponse = { data: ApiSummary[]; page: number; perPage: number; total: number }

async function get<T>(path: string): Promise<T> {
  const base = apiBaseUrl()
  if (base === null) throw new ApiError(0, "unconfigured", "NEXT_PUBLIC_API_URL is not set.")

  let res: Response
  try {
    res = await fetch(`${base}${path}`, { credentials: "include", cache: "no-store" })
  } catch {
    throw new ApiError(0, "network", "Couldn't reach the Zuula API.")
  }
  if (!res.ok) throw new ApiError(res.status, "server_error", `Request failed (${res.status}).`)
  return res.json() as Promise<T>
}

// The API omits a null `ccs` from list responses entirely (dump_report() forces it back to an
// explicit null, but that's the single-report endpoint only — app/schemas/fact_check.py's
// dump_report() docstring). Components check `score.ccs !== null` to decide whether to render
// a percentage at all, so an unrated real report (every one of them, until the community rates
// them) needs that key put back, or `undefined !== null` would show "undefined%".
function normalizeScore(score?: PrecomputedCommunityScore): PrecomputedCommunityScore | undefined {
  return score && { ...score, ccs: score.ccs ?? null }
}

// A real report has no Zuula submission of its own to show — the claim text stands in for it
// (see app/db/real_data.py, the backend side of this same shim) — and list results carry a
// server-computed score rather than raw per-role counts, so `score` goes straight onto
// `community` for communityScore() (lib/community.ts) to return as-is.
function fromSummary(s: ApiSummary): FactCheckReport {
  const zero = { public: 0, journalist: 0, expert: 0 }
  return {
    id: s.id,
    trackingId: s.trackingId,
    title: s.title,
    contentType: s.contentType,
    language: s.language,
    submittedText: `${s.title} ${s.summary}`,
    verdict: s.verdict,
    confidence: s.confidence,
    summary: s.summary,
    whatIsFalse: [],
    whatIsTrue: [],
    claims: [],
    citations: [],
    aiSignals: [],
    annotations: [],
    community: { accurate: zero, inaccurate: zero, comments: [], score: normalizeScore(s.score) },
    category: s.category,
    checkedAt: s.checkedAt,
    processingSeconds: 0,
  }
}

function fromReport(r: ApiReport): FactCheckReport {
  return r as FactCheckReport // same shape; `community.score` is an accepted extra field
}

export function factChecksApiConfigured(): boolean {
  return apiBaseUrl() !== null
}

export async function fetchHomeFeed() {
  const feed = await get<HomeFeedResponse>("/api/v1/fact-checks/home-feed")
  return {
    recent: feed.recent.map(fromSummary),
    debated: feed.debated.map(fromSummary),
    trending: feed.trending,
    leaderboard: feed.leaderboard.map(({ report, score }) => ({
      report: fromSummary(report),
      score: normalizeScore(score)!, // always rated enough to qualify (ccs is never null here)
    })),
  }
}

const LIST_PAGE_SIZE = 50 // the API's max perPage (apps/api/app/api/v1/fact_checks.py)

/** Every listed report, for the Library's client-side search/filter/facet UI (lib/library.ts)
 * to run over exactly as it does today over SAMPLE_REPORTS — a handful of requests at this
 * dataset's size, not meant to scale indefinitely past it. */
export async function fetchAllReportsForLibrary(): Promise<{
  reports: FactCheckReport[]
  categories: string[]
  languages: string[]
}> {
  const reports: FactCheckReport[] = []
  for (let page = 1; ; page++) {
    const res = await get<SearchResponse>(
      `/api/v1/fact-checks?sort=newest&perPage=${LIST_PAGE_SIZE}&page=${page}`
    )
    reports.push(...res.data.map(fromSummary))
    if (reports.length >= res.total || res.data.length === 0) break
  }
  const { categories, languages } = facetsOf(reports)
  return { reports, categories, languages }
}

export async function fetchFullReport(id: string): Promise<FactCheckReport | null> {
  try {
    return fromReport(await get<ApiReport>(`/api/v1/fact-checks/${id}`))
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null
    throw e
  }
}

export async function fetchRelated(id: string, limit: number): Promise<FactCheckReport[]> {
  const items = await get<ApiSummary[]>(`/api/v1/fact-checks/${id}/related?limit=${limit}`)
  return items.map(fromSummary)
}
