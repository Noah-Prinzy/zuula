// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { EMPTY_SUBMISSION } from "@/lib/submission"
import {
  createSubmission,
  followSubmission,
  inputOf,
  submissionsLive,
  type SubmissionStatus,
} from "@/lib/submissions-api"

const fetchMock = vi.fn<typeof fetch>()

function reply(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })
}

const QUEUED: SubmissionStatus = {
  trackingId: "ZL-7K3P-Q9",
  status: "processing",
  submittedAt: "2026-10-28T08:00:00Z",
  steps: [{ step: "received", status: "done" }, { step: "language", status: "active" }],
}

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_API_URL", "http://localhost:8000")
  vi.stubEnv("NEXT_PUBLIC_AUTH_MODE", "api")
  vi.stubGlobal("fetch", fetchMock)
  // jsdom has no EventSource, so followSubmission polls: the fallback path.
  vi.stubGlobal("EventSource", undefined)
  fetchMock.mockReset()
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe("submissions API (FR-SUBMIT-01…06)", () => {
  it("is live unless the build is in demo mode", () => {
    expect(submissionsLive()).toBe(true)
    vi.stubEnv("NEXT_PUBLIC_AUTH_MODE", "demo")
    expect(submissionsLive()).toBe(false)
  })

  it("sends only the active tab's fields", () => {
    const values = { ...EMPTY_SUBMISSION, type: "url" as const, text: "left over", url: " https://x.ug/a ", captchaToken: "tok" }
    expect(inputOf(values)).toEqual({ type: "url", language: "auto", url: "https://x.ug/a", captchaToken: "tok" })
    const article = { ...EMPTY_SUBMISSION, type: "article" as const, headline: "H", body: " Body " }
    expect(inputOf(article)).toEqual({ type: "article", language: "auto", content: "Body", headline: "H" })
  })

  it("posts a text claim as JSON with an idempotency key", async () => {
    fetchMock.mockResolvedValueOnce(
      reply(202, { trackingId: "ZL-7K3P-Q9", status: "queued", estimatedSeconds: 10, statusUrl: "/x" })
    )
    const values = { ...EMPTY_SUBMISSION, text: "Drinking salt water cures malaria, says WhatsApp." }
    await expect(createSubmission(values, { idempotencyKey: "key-1" })).resolves.toMatchObject({
      trackingId: "ZL-7K3P-Q9",
    })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe("http://localhost:8000/api/v1/submissions")
    expect(init?.method).toBe("POST")
    expect((init?.headers as Record<string, string>)["Idempotency-Key"]).toBe("key-1")
    expect(JSON.parse(init?.body as string)).toMatchObject({ type: "text", content: values.text })
  })

  it("follows the pipeline by polling until the report is ready", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    fetchMock
      .mockResolvedValueOnce(reply(200, QUEUED))
      .mockResolvedValueOnce(
        reply(200, { ...QUEUED, status: "completed", result: { id: "fc-2026-0300" } })
      )
    const onStep = vi.fn()
    const done = new Promise<SubmissionStatus>((resolve) =>
      followSubmission("ZL-7K3P-Q9", { onStep, onFinish: resolve, onError: vi.fn() })
    )
    await vi.advanceTimersByTimeAsync(2500)
    await expect(done).resolves.toMatchObject({ status: "completed", result: { id: "fc-2026-0300" } })
    expect(onStep).toHaveBeenCalledWith({ step: "language", status: "active" })
  })

  it("reports an unknown tracking ID instead of polling forever", async () => {
    fetchMock.mockResolvedValue(reply(404, { error: { code: "not_found", message: "No submission." } }))
    const failed = new Promise((resolve) =>
      followSubmission("ZL-AAAA-BB", { onStep: vi.fn(), onFinish: vi.fn(), onError: resolve })
    )
    await expect(failed).resolves.toMatchObject({ status: 404 })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
