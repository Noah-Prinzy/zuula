import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

// Outside Next there's no request to wait for; connection() (render per request) is a no-op.
vi.mock("next/server", () => ({ connection: async () => {} }))

import LibraryPage from "@/app/[locale]/(public)/fact-checks/page"
import { generateMetadata as reportMetadata } from "@/app/[locale]/(public)/fact-checks/[id]/page"
import { SAMPLE_REPORTS } from "@/lib/mock/fact-checks"

// Live builds must never show the invented sample reports, not even when the API fails: the
// Library and a report page throw to the error page (with Retry) instead.
beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_API_URL", "http://localhost:8000")
  vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"))
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.restoreAllMocks()
})

describe("public pages against an unreachable API", () => {
  it("the Library fails instead of listing the sample reports", async () => {
    await expect(LibraryPage()).rejects.toMatchObject({ code: "network" })
  })

  it("a report page fails instead of showing the sample report", async () => {
    const params = Promise.resolve({ id: SAMPLE_REPORTS[0].id })
    await expect(reportMetadata({ params })).rejects.toMatchObject({ code: "network" })
  })
})
