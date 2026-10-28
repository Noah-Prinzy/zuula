// @vitest-environment jsdom
import { screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { renderWithIntl } from "@/test/render"

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
vi.mock("sonner", () => ({ toast }))

import { AdminOverview } from "@/components/admin/admin-overview"
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
  vi.stubGlobal("fetch", fetchMock)
  fetchMock.mockReset()
  toast.success.mockClear()
  toast.error.mockClear()
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
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
})
