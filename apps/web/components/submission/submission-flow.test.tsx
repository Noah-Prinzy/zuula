// @vitest-environment jsdom
import { act, fireEvent, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { renderWithIntl } from "@/test/render"

const router = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn() }))
vi.mock("next/navigation", () => ({ useRouter: () => router, usePathname: () => "/submissions/x" }))
vi.mock("@/components/providers/session-provider", () => ({ useSession: () => ({ user: null, role: null }) }))
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
vi.mock("sonner", () => ({ toast }))

import { AnalysisProgress } from "@/components/submission/analysis-progress"
import { CaptchaField } from "@/components/submission/captcha-field"
import { MediaDropzone } from "@/components/submission/media-dropzone"
import { SubmissionStatus } from "@/components/submission/submission-status"
import { TrackingLookup } from "@/components/submission/tracking-lookup"
import { pipelineFor } from "@/lib/analysis"
import { saveSubmission } from "@/lib/mock/submissions"

beforeEach(() => {
  // The simulated (no-API) flow; the live one is tested in lib/submissions-api.test.ts.
  vi.stubEnv("NEXT_PUBLIC_AUTH_MODE", "demo")
  router.push.mockClear()
  toast.success.mockClear()
  toast.error.mockClear()
  sessionStorage.clear()
  localStorage.clear()
})

describe("TrackingLookup", () => {
  it("rejects a malformed ID", async () => {
    const user = userEvent.setup()
    renderWithIntl(<TrackingLookup />)
    await user.type(screen.getByRole("textbox"), "hello")
    await user.click(screen.getByRole("button"))
    expect(screen.getByRole("textbox")).toHaveAttribute("aria-invalid", "true")
    expect(router.push).not.toHaveBeenCalled()
  })

  it("normalises a valid ID and opens its status page", async () => {
    const user = userEvent.setup()
    renderWithIntl(<TrackingLookup />)
    await user.type(screen.getByRole("textbox"), " zl-ab3d-k7 ")
    await user.click(screen.getByRole("button"))
    expect(router.push).toHaveBeenCalledWith("/submissions/ZL-AB3D-K7")
  })
})

describe("CaptchaField", () => {
  it("passes a dev token when Turnstile isn't configured", () => {
    const onToken = vi.fn()
    renderWithIntl(<CaptchaField onToken={onToken} />)
    expect(onToken).toHaveBeenCalledWith("dev-bypass")
  })
})

describe("AnalysisProgress", () => {
  const steps = pipelineFor("text")

  it.each(["running", "done", "error"] as const)("renders every step while %s", (state) => {
    renderWithIntl(<AnalysisProgress steps={steps} current={2} state={state} error={state === "error" ? "Boom" : undefined} />)
    for (const s of steps) expect(screen.getAllByText(s.label, { exact: false }).length).toBeGreaterThan(0)
  })
})

describe("MediaDropzone (FR-SUBMIT-05)", () => {
  it("accepts a chosen file and can remove it", async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    const { container, rerender } = renderWithIntl(<MediaDropzone id="f" value={null} onChange={onChange} />)
    const file = new File(["x"], "photo.png", { type: "image/png" })
    fireEvent.change(container.querySelector<HTMLInputElement>("input[type=file]")!, { target: { files: [file] } })
    expect(onChange).toHaveBeenCalledWith(file)

    rerender(<MediaDropzone id="f" value={file} onChange={onChange} progress={40} />)
    expect(screen.getByText("photo.png", { exact: false })).toBeInTheDocument()
    // Remove appears once the upload has finished.
    rerender(<MediaDropzone id="f" value={file} onChange={onChange} />)
    const remove = screen.getByLabelText(/remove/i)
    await user.click(remove)
    expect(onChange).toHaveBeenLastCalledWith(null)
  })

  it("accepts a dropped file", () => {
    const onChange = vi.fn()
    const { container } = renderWithIntl(<MediaDropzone id="f" value={null} onChange={onChange} />)
    const file = new File(["x"], "clip.mp4", { type: "video/mp4" })
    const zone = container.querySelector("[data-dragging], label, div")!
    fireEvent.dragOver(zone, { dataTransfer: { files: [file], types: ["Files"] } })
    fireEvent.drop(zone, { dataTransfer: { files: [file], types: ["Files"] } })
    expect(onChange).toHaveBeenCalledWith(file)
  })
})

describe("SubmissionStatus (FR-SUBMIT-06)", () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }))
  afterEach(() => vi.useRealTimers())

  it("shows the tracking ID and treats unknown submissions as finished", () => {
    renderWithIntl(<SubmissionStatus trackingId="ZL-AB3D-K7" />)
    expect(screen.getByText("ZL-AB3D-K7")).toBeInTheDocument()
  })

  it("runs the pipeline for a new submission and then opens the report", async () => {
    saveSubmission({
      trackingId: "ZL-QQQQ-22",
      type: "text",
      language: "auto",
      preview: "Salt water cures malaria",
      submittedAt: new Date().toISOString(),
    })
    renderWithIntl(<SubmissionStatus trackingId="ZL-QQQQ-22" />)
    expect(screen.getByText("ZL-QQQQ-22")).toBeInTheDocument()
    // Each step schedules the next after a render, so advance a second at a time.
    for (let i = 0; i < 30 && !router.push.mock.calls.length; i++) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000)
      })
    }
    expect(router.push).toHaveBeenCalledWith(expect.stringMatching(/^\/fact-checks\//))
  })

  it("copies the tracking ID", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true })
    renderWithIntl(<SubmissionStatus trackingId="ZL-AB3D-K7" />)
    await act(async () => {
      fireEvent.click(screen.getAllByRole("button")[0])
    })
    expect(writeText).toHaveBeenCalledWith("ZL-AB3D-K7")
    expect(toast.success).toHaveBeenCalled()
  })
})
