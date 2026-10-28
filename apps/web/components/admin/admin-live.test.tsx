// @vitest-environment jsdom
import { screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { renderWithIntl } from "@/test/render"

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
vi.mock("sonner", () => ({ toast }))
vi.mock("@/components/providers/session-provider", () => ({ useSession: () => ({ user: { name: "Noah", email: "n@x", role: "admin" } }) }))

import { AdminOverview } from "@/components/admin/admin-overview"
import { AuditLog } from "@/components/admin/audit-log"
import { Broadcasts } from "@/components/admin/broadcasts"
import { Moderation } from "@/components/admin/moderation"
import { PlatformSettingsForm } from "@/components/admin/platform-settings"
import { SourceManager } from "@/components/admin/source-manager"
import { TrendReports } from "@/components/admin/trend-reports"
import { UserManagement } from "@/components/admin/user-management"

const fetchMock = vi.fn<typeof fetch>()
const reply = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })

const NOAH = {
  id: "usr_41ed",
  name: "Noah Admin",
  email: "noah@example.ug",
  role: "public",
  status: "active",
  joined: "2026-10-27",
  lastActive: "2026-10-28",
  ratings: 3,
}

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_API_URL", "http://localhost:8000")
  vi.stubEnv("NEXT_PUBLIC_AUTH_MODE", "api")
  // A spy, not stubGlobal: unstubAllGlobals would also drop test/setup.ts's ResizeObserver stub.
  vi.spyOn(globalThis, "fetch").mockImplementation(fetchMock)
  fetchMock.mockReset()
  toast.success.mockClear()
  toast.error.mockClear()
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.restoreAllMocks()
})

describe("admin screens against the API (Phase 2)", () => {
  it("Overview shows the API's targets, not the sample ones", async () => {
    fetchMock.mockResolvedValueOnce(
      reply(200, {
        kpis: [{ id: "live-kpi", label: "Live KPI from the API", value: 42, unit: "%", target: 40, direction: "min", note: "n" }],
        dailyChecks: [{ date: "2026-10-28", checks: 7 }],
        verdictMix: [{ verdict: "false", count: 3 }],
        systemHealth: [{ label: "Database", value: "ok", ok: true, note: "" }],
      })
    )
    renderWithIntl(<AdminOverview />)
    expect(await screen.findByText("Live KPI from the API")).toBeInTheDocument()
    expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:8000/api/v1/admin/overview")
  })

  it("Users lists the API's users, filtered and paged by the API", async () => {
    fetchMock.mockResolvedValueOnce(reply(200, { data: [NOAH], page: 1, perPage: 50, total: 1 }))
    renderWithIntl(<UserManagement />)
    expect(await screen.findByText("Noah Admin")).toBeInTheDocument()
    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/v1/admin/users?page=1&perPage=50")
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1)) // and no refetch loop
  })

  const page = (data: unknown[]) => ({ data, page: 1, perPage: 100, total: data.length })
  const SETTINGS = {
    thresholds: { verifiedMin: 90, questionedMin: 40, questionedMax: 69, questionedRatings: 50, escalatedMax: 39, escalatedRatings: 100, suspendedMax: 19, suspendedRatings: 200 },
    weights: { public: 1, journalist: 2, expert: 5 },
    slaHours: 48,
    apiRateLimit: 100,
    retraining: { cadence: "weekly", minCcs: 85 },
  }
  it.each([
    ["Audit log", <AuditLog key="a" />, ["/api/v1/admin/audit-log?page=1&perPage=100"], [page([{ id: "1", at: "2026-10-28T08:00:00Z", actor: "Maintenance", actorRole: "admin", action: "accreditation.approve", target: "u5", detail: "Live audit row", ip: "" }])]],
    ["Reports", <TrendReports key="r" />, ["/api/v1/admin/reports"], [[{ month: "2026-10", checks: 12, falseShare: 40, aiGenerated: 2, topCategories: ["Health"], avgDelivery: 9 }]]],
    ["Settings", <PlatformSettingsForm key="s" />, ["/api/v1/admin/settings"], [SETTINGS]],
    ["Moderation", <Moderation key="m" />, ["/api/v1/admin/moderation/reports?perPage=100", "/api/v1/admin/moderation/signals"], [page([]), []]],
    ["Sources", <SourceManager key="so" />, ["/api/v1/admin/sources?perPage=100"], [page([{ id: "s1", name: "Live Source Daily", domain: "live.ug", type: "media", languages: ["English"], tier: 1, active: true, lastCrawled: "2026-10-28T08:00:00Z", crawlOk: true }])]],
    ["Broadcasts", <Broadcasts key="b" />, ["/api/v1/admin/broadcasts"], [[]]],
  ])("%s loads from the API", async (_name, ui, paths, bodies) => {
    bodies.forEach((b) => fetchMock.mockResolvedValueOnce(reply(200, b)))
    renderWithIntl(ui)
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(paths.length))
    const called = fetchMock.mock.calls.map((c) => String(c[0]).replace("http://localhost:8000", ""))
    expect(called.sort()).toEqual([...paths].sort())
    expect(toast.error).not.toHaveBeenCalled()
  })
})
