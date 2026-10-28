// SAMPLE DATA for the Admin area. Replaced by the admin API in Phase 3.

import type { Role } from "@/lib/roles"
import type { AccreditationApplicationDetail } from "@/lib/verification-api"
import type { Verdict } from "@/lib/types/fact-check"

// ---- KPIs (§13, year-one targets) ----

export type Kpi = {
  id: string
  label: string
  value: number
  unit: "%" | "s" | "h" | "" | "/5"
  target: number
  /** "min": value should be ≥ target; "max": value should be ≤ target. */
  direction: "min" | "max"
  note: string
}

export const KPIS: Kpi[] = [
  { id: "f1", label: "Text detection F1", value: 91.4, unit: "%", target: 90, direction: "min", note: "Held-out Ugandan test set, Sep eval" },
  { id: "deepfake", label: "Deepfake accuracy", value: 83.1, unit: "%", target: 85, direction: "min", note: "Image + video benchmark" },
  { id: "mau", label: "Monthly active users", value: 38_420, unit: "", target: 50_000, direction: "min", note: "Unique signed-in and anonymous" },
  { id: "latency", label: "Avg text verdict time", value: 7.3, unit: "s", target: 10, direction: "max", note: "p50 over the last 7 days" },
  { id: "ratings", label: "Ratings per verdict", value: 31, unit: "", target: 25, direction: "min", note: "Mean over the last 30 days" },
  { id: "turnaround", label: "Expert turnaround", value: 19.6, unit: "h", target: 48, direction: "max", note: "Mean, last 30 days" },
  { id: "partners", label: "API partners", value: 6, unit: "", target: 10, direction: "min", note: "Organisations with an active key" },
  { id: "languages", label: "Languages supported", value: 5, unit: "", target: 5, direction: "min", note: "English, Luganda, Acholi, Runyankole, Ateso" },
]

export function kpiMet(k: Kpi) {
  return k.direction === "min" ? k.value >= k.target : k.value <= k.target
}

// Checks per day, last 14 days (ends 21 Sep 2026).
export const DAILY_CHECKS = [
  412, 438, 391, 460, 522, 498, 350, 377, 541, 603, 587, 612, 455, 489,
].map((checks, i) => {
  const d = new Date("2026-09-08T00:00:00+03:00")
  d.setDate(d.getDate() + i)
  return { date: d.toISOString().slice(0, 10), checks }
})

export const VERDICT_MIX: { verdict: Verdict; count: number }[] = [
  { verdict: "false", count: 1840 },
  { verdict: "likely-false", count: 1210 },
  { verdict: "authentic", count: 980 },
  { verdict: "ai-generated", count: 640 },
  { verdict: "unverifiable", count: 565 },
]

export const SYSTEM_HEALTH = [
  { label: "API uptime (30 days)", value: "99.82%", ok: true, note: "SLA 99.5%" },
  { label: "Analysis queue", value: "14 jobs", ok: true, note: "Oldest 38 s" },
  { label: "AI model", value: "zuula-verify 0.3", ok: true, note: "Retrained 14 Sep" },
  { label: "Source crawler", value: "2 sources failing", ok: false, note: "See Sources" },
]

// ---- Users (FR-ADMIN-02) ----

export type UserStatus = "active" | "suspended" | "pending"

export type AdminUser = {
  id: string
  name: string
  email: string
  role: Role
  status: UserStatus
  joined: string
  lastActive: string
  ratings: number
}

export const SAMPLE_USERS: AdminUser[] = [
  { id: "u1", name: "Mary Akello", email: "mary@example.com", role: "admin", status: "active", joined: "2026-01-12", lastActive: "2026-09-21", ratings: 12 },
  { id: "u2", name: "David Okello", email: "david@example.com", role: "expert", status: "active", joined: "2026-02-03", lastActive: "2026-09-21", ratings: 88 },
  { id: "u3", name: "Esther Atim", email: "esther@example.com", role: "expert", status: "active", joined: "2026-03-18", lastActive: "2026-09-20", ratings: 64 },
  { id: "u4", name: "Sarah Namutebi", email: "sarah@example.com", role: "journalist", status: "active", joined: "2026-04-09", lastActive: "2026-09-21", ratings: 142 },
  { id: "u5", name: "Grace Nankya", email: "grace@example.com", role: "journalist", status: "pending", joined: "2026-09-19", lastActive: "2026-09-19", ratings: 3 },
  { id: "u6", name: "Amina Nakato", email: "amina@example.com", role: "public", status: "active", joined: "2026-05-22", lastActive: "2026-09-21", ratings: 37 },
  { id: "u7", name: "James Ssentongo", email: "james@example.com", role: "public", status: "active", joined: "2026-06-30", lastActive: "2026-09-18", ratings: 21 },
  { id: "u8", name: "Peter Wabwire", email: "peter@example.com", role: "public", status: "suspended", joined: "2026-07-14", lastActive: "2026-09-02", ratings: 410 },
  { id: "u9", name: "Joseph Opio", email: "joseph@example.com", role: "public", status: "active", joined: "2026-08-01", lastActive: "2026-09-20", ratings: 9 },
]

// ---- Accreditation (FR-AUTH-02) ----

// The demo queue when there's no API (components/admin/verification-review.tsx). Same shape as
// GET /admin/verifications/{id}; documents have no links because there's nothing to download.
export const SAMPLE_APPLICATIONS: AccreditationApplicationDetail[] = [
  {
    id: "acc-u5",
    status: "pending",
    requestedRole: "journalist",
    organisation: "Daily Monitor",
    pressCardNumber: "UMC-2026-0412",
    submittedAt: "2026-09-19T08:12:00Z",
    documentCount: 0,
    documents: [],
    applicant: { id: "u5", name: "Grace Nankya", email: "grace@example.com", role: "journalist", status: "pending", joined: "2026-09-19" },
  },
  {
    id: "acc-u7",
    status: "pending",
    requestedRole: "expert",
    organisation: "Makerere University School of Public Health",
    submittedAt: "2026-09-20T14:40:00Z",
    documentCount: 0,
    documents: [],
    applicant: { id: "u7", name: "James Ssentongo", email: "james@example.com", role: "public", status: "active", district: "Wakiso", joined: "2026-06-30" },
  },
  {
    id: "acc-u4",
    status: "approved",
    requestedRole: "journalist",
    organisation: "Nile Post",
    submittedAt: "2026-04-09T10:00:00Z",
    reviewedAt: "2026-04-10T09:30:00Z",
    reviewer: "Mary Akello",
    documentCount: 0,
    documents: [],
    applicant: { id: "u4", name: "Sarah Namutebi", email: "sarah@example.com", role: "journalist", status: "active", joined: "2026-04-09" },
  },
]

// ---- Moderation (FR-RATE-07) ----

export type ContentReport = {
  id: string
  reportId: string
  title: string
  reason: string
  reporters: number
  sample: string
  reportedAt: string
}

export const CONTENT_REPORTS: ContentReport[] = [
  { id: "cr1", reportId: "fc-2026-0159", title: "“All schools to close for the rest of the term next week”", reason: "Verdict seems wrong", reporters: 14, sample: "Our head teacher received this letter officially.", reportedAt: "2026-09-21T06:45:00+03:00" },
  { id: "cr2", reportId: "fc-2026-0157", title: "Photo of flooded Kampala road shared as “today”", reason: "Outdated information", reporters: 6, sample: "Road was flooded again this morning.", reportedAt: "2026-09-21T09:20:00+03:00" },
  { id: "cr3", reportId: "fc-2026-0161", title: "“Boiled banana leaves cure malaria in three days”", reason: "Offensive comment", reporters: 3, sample: "A comment on this report contains insults.", reportedAt: "2026-09-20T22:10:00+03:00" },
]

export type ManipulationSignal = {
  id: string
  reportId: string
  title: string
  pattern: string
  accounts: number
  window: string
  direction: "accurate" | "inaccurate"
  confidence: number
}

export const MANIPULATION_SIGNALS: ManipulationSignal[] = [
  { id: "ms1", reportId: "fc-2026-0152", title: "Speech clip attributed to a district official", pattern: "Accounts created in the last 48 h from the same network range", accounts: 132, window: "11 minutes", direction: "inaccurate", confidence: 0.92 },
  { id: "ms2", reportId: "fc-2026-0155", title: "“Voting will move to mobile phones at the next election”", pattern: "Identical rating comments posted within seconds", accounts: 41, window: "3 minutes", direction: "inaccurate", confidence: 0.78 },
]

// ---- Trusted sources (FR-ADMIN-03, FR-DETECT-06) ----

export type SourceType = "media" | "government" | "fact-checker" | "international" | "academic"

export type TrustedSource = {
  id: string
  name: string
  domain: string
  type: SourceType
  languages: string[]
  tier: 1 | 2 | 3
  active: boolean
  lastCrawled: string
  crawlOk: boolean
}

export const SOURCE_TYPE_LABELS: Record<SourceType, string> = {
  media: "Media house",
  government: "Government",
  "fact-checker": "Fact-checker",
  international: "International",
  academic: "Academic",
}

export const SAMPLE_SOURCES: TrustedSource[] = [
  { id: "s1", name: "New Vision", domain: "newvision.co.ug", type: "media", languages: ["English"], tier: 1, active: true, lastCrawled: "2026-09-21T11:40:00+03:00", crawlOk: true },
  { id: "s2", name: "Daily Monitor", domain: "monitor.co.ug", type: "media", languages: ["English"], tier: 1, active: true, lastCrawled: "2026-09-21T11:35:00+03:00", crawlOk: true },
  { id: "s3", name: "Bukedde", domain: "bukedde.co.ug", type: "media", languages: ["Luganda"], tier: 1, active: true, lastCrawled: "2026-09-21T11:20:00+03:00", crawlOk: true },
  { id: "s4", name: "Nile Post", domain: "nilepost.co.ug", type: "media", languages: ["English"], tier: 2, active: true, lastCrawled: "2026-09-21T10:50:00+03:00", crawlOk: true },
  { id: "s5", name: "Uganda Radio Network", domain: "ugandaradionetwork.net", type: "media", languages: ["English", "Luganda", "Acholi"], tier: 1, active: true, lastCrawled: "2026-09-21T11:05:00+03:00", crawlOk: false },
  { id: "s6", name: "Ministry of Health", domain: "health.go.ug", type: "government", languages: ["English"], tier: 1, active: true, lastCrawled: "2026-09-21T09:00:00+03:00", crawlOk: true },
  { id: "s7", name: "Electoral Commission", domain: "ec.or.ug", type: "government", languages: ["English"], tier: 1, active: true, lastCrawled: "2026-09-21T08:30:00+03:00", crawlOk: true },
  { id: "s8", name: "Uganda Communications Commission", domain: "ucc.co.ug", type: "government", languages: ["English"], tier: 1, active: true, lastCrawled: "2026-09-21T08:45:00+03:00", crawlOk: false },
  { id: "s9", name: "Africa Check", domain: "africacheck.org", type: "fact-checker", languages: ["English"], tier: 1, active: true, lastCrawled: "2026-09-21T10:15:00+03:00", crawlOk: true },
  { id: "s10", name: "PesaCheck", domain: "pesacheck.org", type: "fact-checker", languages: ["English"], tier: 1, active: true, lastCrawled: "2026-09-21T10:10:00+03:00", crawlOk: true },
  { id: "s11", name: "Reuters", domain: "reuters.com", type: "international", languages: ["English"], tier: 2, active: true, lastCrawled: "2026-09-21T11:00:00+03:00", crawlOk: true },
  { id: "s12", name: "Makerere University AI Lab", domain: "air.ug", type: "academic", languages: ["English"], tier: 3, active: false, lastCrawled: "2026-08-30T12:00:00+03:00", crawlOk: true },
]

export const SOURCE_TARGET = 50 // FR-DETECT-06: at least 50 source databases

// ---- Broadcasts (FR-ADMIN-05) ----

export type Broadcast = {
  id: string
  title: string
  message: string
  severity: "high" | "critical"
  audience: string
  channels: string[]
  sentAt: string
  sentBy: string
  reach: number
  opened: number
}

export const SAMPLE_BROADCASTS: Broadcast[] = [
  { id: "b3", title: "Health misinformation: false malaria cure", message: "A message claiming boiled banana leaves cure malaria is spreading on WhatsApp. It is false. Get tested and use approved treatment.", severity: "high", audience: "Everyone in Central region", channels: ["In-app", "Push", "SMS"], sentAt: "2026-09-21T08:15:00+03:00", sentBy: "Mary Akello", reach: 18_430, opened: 9_874 },
  { id: "b2", title: "Scam alert: fake free-data links", message: "Links offering free mobile data for your National ID number are phishing. Don't enter your details.", severity: "critical", audience: "Everyone", channels: ["In-app", "Push", "Email", "SMS"], sentAt: "2026-09-16T14:02:00+03:00", sentBy: "Mary Akello", reach: 41_205, opened: 22_950 },
]

// ---- Monthly reports (FR-ADMIN-04) ----

export type MonthlyReport = {
  month: string // YYYY-MM
  checks: number
  falseShare: number // % False or Likely False
  aiGenerated: number
  topCategories: string[]
  avgDelivery: number // seconds
}

export const MONTHLY_REPORTS: MonthlyReport[] = [
  { month: "2026-04", checks: 4_120, falseShare: 52, aiGenerated: 210, topCategories: ["Health", "Politics", "Economy"], avgDelivery: 9.4 },
  { month: "2026-05", checks: 6_380, falseShare: 55, aiGenerated: 344, topCategories: ["Politics", "Health", "Education"], avgDelivery: 8.9 },
  { month: "2026-06", checks: 8_905, falseShare: 58, aiGenerated: 512, topCategories: ["Elections", "Politics", "Health"], avgDelivery: 8.1 },
  { month: "2026-07", checks: 10_240, falseShare: 57, aiGenerated: 690, topCategories: ["Economy", "Technology", "Health"], avgDelivery: 7.8 },
  { month: "2026-08", checks: 12_870, falseShare: 54, aiGenerated: 905, topCategories: ["Technology", "Economy", "Education"], avgDelivery: 7.5 },
  { month: "2026-09", checks: 9_105, falseShare: 56, aiGenerated: 744, topCategories: ["Health", "Education", "Economy"], avgDelivery: 7.3 },
]

export function monthLabel(ym: string) {
  return new Date(`${ym}-01T00:00:00`).toLocaleDateString("en-GB", { month: "long", year: "numeric" })
}

// ---- Audit log (FR-ADMIN-07, FR-REVIEW-03) ----

export type AuditAction =
  | "verdict.override"
  | "verdict.confirm"
  | "user.role_change"
  | "user.suspend"
  | "user.reinstate"
  | "source.add"
  | "source.deactivate"
  | "broadcast.send"
  | "settings.update"
  | "moderation.remove"

export type AuditEntry = {
  id: string
  at: string
  actor: string
  actorRole: Role
  action: AuditAction
  target: string
  detail: string
  ip: string
}

export const AUDIT_ACTION_LABELS: Record<AuditAction, string> = {
  "verdict.override": "Verdict overridden",
  "verdict.confirm": "Verdict confirmed",
  "user.role_change": "Role changed",
  "user.suspend": "User suspended",
  "user.reinstate": "User reinstated",
  "source.add": "Source added",
  "source.deactivate": "Source deactivated",
  "broadcast.send": "Broadcast sent",
  "settings.update": "Settings changed",
  "moderation.remove": "Content removed",
}

export const SAMPLE_AUDIT: AuditEntry[] = [
  { id: "a12", at: "2026-09-21T11:02:00+03:00", actor: "Mary Akello", actorRole: "admin", action: "settings.update", target: "Escalation thresholds", detail: "Questioned: min ratings 40 → 50", ip: "196.43.x.x" },
  { id: "a11", at: "2026-09-21T08:15:00+03:00", actor: "Mary Akello", actorRole: "admin", action: "broadcast.send", target: "b3", detail: "Health misinformation: false malaria cure (Central)", ip: "196.43.x.x" },
  { id: "a10", at: "2026-09-20T17:40:00+03:00", actor: "Mary Akello", actorRole: "admin", action: "user.role_change", target: "Esther Atim", detail: "Public User → Expert Reviewer", ip: "196.43.x.x" },
  { id: "a9", at: "2026-09-19T14:20:00+03:00", actor: "David Okello", actorRole: "expert", action: "verdict.confirm", target: "fc-2026-0142", detail: "False confirmed: “Verified with the Ministry…”", ip: "102.85.x.x" },
  { id: "a8", at: "2026-09-18T10:05:00+03:00", actor: "Mary Akello", actorRole: "admin", action: "user.suspend", target: "Peter Wabwire", detail: "Coordinated rating activity (ms-0031)", ip: "196.43.x.x" },
  { id: "a7", at: "2026-09-17T18:05:00+03:00", actor: "David Okello", actorRole: "expert", action: "verdict.override", target: "fc-2026-0154", detail: "False → Likely False: “Photo is genuine but from 2020…”", ip: "102.85.x.x" },
  { id: "a6", at: "2026-09-16T14:02:00+03:00", actor: "Mary Akello", actorRole: "admin", action: "broadcast.send", target: "b2", detail: "Scam alert: fake free-data links (Everyone)", ip: "196.43.x.x" },
  { id: "a5", at: "2026-09-15T09:30:00+03:00", actor: "Mary Akello", actorRole: "admin", action: "source.add", target: "Bukedde", detail: "Media house, Luganda, tier 1", ip: "196.43.x.x" },
  { id: "a4", at: "2026-09-12T16:45:00+03:00", actor: "Mary Akello", actorRole: "admin", action: "moderation.remove", target: "Comment on fc-2026-0139", detail: "Abusive language", ip: "196.43.x.x" },
  { id: "a3", at: "2026-09-10T12:00:00+03:00", actor: "Mary Akello", actorRole: "admin", action: "source.deactivate", target: "Makerere University AI Lab", detail: "Feed discontinued", ip: "196.43.x.x" },
]

// ---- Platform settings (FR-ADMIN-06) ----

export const DEFAULT_SETTINGS = {
  thresholds: {
    verifiedMin: 90,
    questionedMin: 40,
    questionedMax: 69,
    questionedRatings: 50,
    escalatedMax: 39,
    escalatedRatings: 100,
    suspendedMax: 19,
    suspendedRatings: 200,
  },
  weights: { public: 1, journalist: 2, expert: 5 },
  slaHours: 48,
  apiRateLimit: 100,
  retraining: { cadence: "weekly" as "weekly" | "monthly", minCcs: 85 },
}

export type PlatformSettings = typeof DEFAULT_SETTINGS
