// @vitest-environment jsdom
import { screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { renderWithIntl } from "@/test/render"

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }))
vi.mock("sonner", () => ({ toast }))

import { ActivityList } from "@/components/account/activity-list"
import { AlertSettings } from "@/components/account/alert-settings"
import { ApiKeys } from "@/components/account/api-keys"

const fetchMock = vi.fn<typeof fetch>()
const reply = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })
const page = (data: unknown[]) => ({ data, page: 1, perPage: 100, total: data.length })

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_API_URL", "http://localhost:8000")
  vi.stubEnv("NEXT_PUBLIC_AUTH_MODE", "api")
  // A spy, not stubGlobal: unstubAllGlobals would also drop test/setup.ts's ResizeObserver stub.
  vi.spyOn(globalThis, "fetch").mockImplementation(fetchMock)
  fetchMock.mockReset()
  toast.error.mockClear()
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.restoreAllMocks()
})

const called = () => fetchMock.mock.calls.map((c) => String(c[0]).replace("http://localhost:8000", "")).sort()

describe("account screens against the API (Phase 2)", () => {
  it("Activity shows your own submissions from the API", async () => {
    fetchMock.mockImplementation(async (url) =>
      String(url).includes("/me/submissions")
        ? reply(200, page([{ trackingId: "ZL-7K3P-Q9", type: "text", preview: "A live submission preview", submittedAt: "2026-10-28T08:00:00Z", status: "processing" }]))
        : reply(200, page([]))
    )
    renderWithIntl(<ActivityList />)
    expect(await screen.findByText(/A live submission preview/)).toBeInTheDocument()
    expect(called()).toEqual(["/api/v1/me/ratings?perPage=100", "/api/v1/me/submissions?perPage=100"])
  })

  it("Alerts loads your settings and API keys loads keys and usage", async () => {
    fetchMock.mockImplementation(async (url) => {
      const u = String(url)
      if (u.endsWith("/me/alert-settings")) return reply(200, { topics: ["health"], notifyOn: {}, channels: { inApp: true } })
      if (u.endsWith("/me/api-usage")) return reply(200, { usedThisHour: 3, last24h: 9 })
      return reply(200, [])
    })
    renderWithIntl(
      <>
        <AlertSettings />
        <ApiKeys />
      </>
    )
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
    expect(called()).toEqual(["/api/v1/me/alert-settings", "/api/v1/me/api-keys", "/api/v1/me/api-usage"])
    await waitFor(() => expect(screen.getByText(/3 \/ 100/)).toBeInTheDocument())
    expect(toast.error).not.toHaveBeenCalled()
  })
})
