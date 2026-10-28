// @vitest-environment jsdom
import { screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { renderWithIntl } from "@/test/render"

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }))
vi.mock("sonner", () => ({ toast }))
vi.mock("@/components/providers/session-provider", () => ({
  useSession: () => ({ user: { id: "usr_1", name: "Dr. Sarah Nakato", role: "expert" } }),
}))

import { CaseReview } from "@/components/review/case-review"
import { ReviewHistory } from "@/components/review/review-history"
import { ReviewQueue } from "@/components/review/review-queue"
import { SAMPLE_CASES, SAMPLE_DECISIONS } from "@/lib/mock/review"
import { SAMPLE_REPORTS } from "@/lib/mock/fact-checks"

// Live builds must never show the invented sample cases, decisions or reports, not even when
// the API fails: they would pass for real fact-checks.
const fetchMock = vi.fn<typeof fetch>()
const reply = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })

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

const caseReport = SAMPLE_REPORTS.find((r) => r.id === SAMPLE_CASES[0].reportId)!

describe("review screens against a failing API", () => {
  it("History shows an error, not the sample decisions", async () => {
    fetchMock.mockResolvedValue(reply(500, { error: { code: "server_error", message: "down" } }))
    renderWithIntl(<ReviewHistory />)
    await waitFor(() => expect(toast.error).toHaveBeenCalled())
    expect(screen.queryByText(SAMPLE_DECISIONS[0].title)).not.toBeInTheDocument()
  })

  it("Queue shows an error, not the sample cases", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"))
    renderWithIntl(<ReviewQueue />)
    await waitFor(() => expect(toast.error).toHaveBeenCalled())
    expect(screen.queryByText(caseReport.title)).not.toBeInTheDocument()
  })

  it("a case the API doesn't have is not found, never the sample case", async () => {
    fetchMock.mockResolvedValue(reply(404, { error: { code: "not_found", message: "No such case." } }))
    renderWithIntl(<CaseReview caseId={SAMPLE_CASES[0].id} />)
    expect(await screen.findByText(/already been decided, or the link is wrong/)).toBeInTheDocument()
    expect(screen.queryByText(caseReport.title)).not.toBeInTheDocument()
  })
})
