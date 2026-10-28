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

describe("the sample-report notice", () => {
  it("marks only the fictional seed reports, not ones the pipeline made", async () => {
    const { isSampleReport } = await import("@/lib/mock/fact-checks")
    expect(isSampleReport("fc-2026-0142")).toBe(true)
    expect(isSampleReport("fc-2026-0165")).toBe(false) // made by the pipeline on 28 Oct 2026
    expect(isSampleReport("fc-real-0001")).toBe(false)
  })

  it("knows every report the API seeds as sample data", async () => {
    const { readFileSync } = await import("node:fs")
    const seeded = readFileSync("../api/app/db/sample_data/fact_checks.py", "utf8").match(/fc-\d{4}-\d{4}/g) ?? []
    expect(seeded.length).toBeGreaterThan(0)
    for (const id of new Set(seeded)) expect(SAMPLE_REPORTS.map((r) => r.id)).toContain(id)
  })
})
