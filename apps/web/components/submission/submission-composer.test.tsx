// @vitest-environment jsdom
import { fireEvent, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import type { Role } from "@/lib/roles"
import { renderWithIntl } from "@/test/render"

const router = vi.hoisted(() => ({ push: vi.fn() }))
vi.mock("next/navigation", () => ({ useRouter: () => router, usePathname: () => "/verify" }))
const session = vi.hoisted(() => ({ role: "public" as Role | null }))
vi.mock("@/components/providers/session-provider", () => ({
  useSession: () => ({ user: session.role ? { name: "T", email: "t@x", role: session.role } : null, role: session.role }),
}))
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
vi.mock("sonner", () => ({ toast }))
vi.mock("@/components/shell/route-progress", () => ({ startNavigationProgress: vi.fn() }))

import { SubmissionComposer } from "@/components/submission/submission-composer"
import { getSubmission } from "@/lib/mock/submissions"
import { TRACKING_ID_PATTERN } from "@/lib/analysis"

const CLAIM = "Drinking salt water every morning cures malaria, says a message on WhatsApp."
const submitButton = () => screen.getByRole("button", { name: /verify|check|submit/i })

beforeEach(() => {
  // The simulated (no-API) flow; the live one is tested in lib/submissions-api.test.ts.
  vi.stubEnv("NEXT_PUBLIC_AUTH_MODE", "demo")
  session.role = "public"
  router.push.mockClear()
  toast.success.mockClear()
  toast.error.mockClear()
  localStorage.clear()
  sessionStorage.clear()
})

describe("SubmissionComposer (FR-SUBMIT-01)", () => {
  it("offers text, link, media and article tabs", () => {
    renderWithIntl(<SubmissionComposer />)
    expect(screen.getAllByRole("tab")).toHaveLength(4)
    expect(screen.getByRole("form")).toBeInTheDocument()
  })

  it("rejects text that is too short, without submitting", async () => {
    const user = userEvent.setup()
    renderWithIntl(<SubmissionComposer />)
    await user.type(screen.getByRole("textbox"), "too short")
    await user.click(submitButton())
    expect(await screen.findByRole("textbox")).toHaveAttribute("aria-invalid", "true")
    expect(router.push).not.toHaveBeenCalled()
  })

  it("submits a valid claim, stores it and opens its status page", async () => {
    const user = userEvent.setup()
    renderWithIntl(<SubmissionComposer />)
    await user.click(screen.getByRole("textbox"))
    await user.paste(CLAIM)
    await user.click(submitButton())

    await waitFor(() => expect(router.push).toHaveBeenCalledTimes(1), { timeout: 3000 })
    const url = router.push.mock.calls[0][0] as string
    const trackingId = url.replace("/submissions/", "")
    expect(url).toMatch(/^\/submissions\//)
    expect(TRACKING_ID_PATTERN.test(trackingId)).toBe(true)
    expect(getSubmission(trackingId)).toMatchObject({ trackingId, type: "text" })
    expect(toast.success).toHaveBeenCalled()
  })

  it("submits with Ctrl+Enter from the text box", async () => {
    const user = userEvent.setup()
    renderWithIntl(<SubmissionComposer variant="compact" />)
    const box = screen.getByRole("textbox")
    await user.click(box)
    await user.paste(CLAIM)
    fireEvent.keyDown(box, { key: "Enter", ctrlKey: true })
    await waitFor(() => expect(router.push).toHaveBeenCalled(), { timeout: 3000 })
  })

  it("lets signed-out visitors submit once the (dev) human check passes", async () => {
    session.role = null
    const user = userEvent.setup()
    renderWithIntl(<SubmissionComposer />)
    await user.click(screen.getByRole("textbox"))
    await user.paste(CLAIM)
    await user.click(submitButton())
    await waitFor(() => expect(router.push).toHaveBeenCalled(), { timeout: 3000 })
    expect(toast.error).not.toHaveBeenCalled()
  })

  it("validates links on the Link tab", async () => {
    const user = userEvent.setup()
    const { container } = renderWithIntl(<SubmissionComposer />)
    await user.click(screen.getAllByRole("tab")[1])
    const url = container.querySelector<HTMLInputElement>("#submit-url")!
    await user.type(url, "not a link")
    await user.click(submitButton())
    await waitFor(() => expect(url).toHaveAttribute("aria-invalid", "true"))

    await user.clear(url)
    await user.type(url, "https://example.com/story")
    await user.click(submitButton())
    await waitFor(() => expect(router.push).toHaveBeenCalled(), { timeout: 3000 })
  })

  it("needs a body on the Article tab", async () => {
    const user = userEvent.setup()
    const { container } = renderWithIntl(<SubmissionComposer />)
    await user.click(screen.getAllByRole("tab")[3])
    await user.click(submitButton())
    await waitFor(() => expect(container.querySelector("#submit-body")).toHaveAttribute("aria-invalid", "true"))
    expect(router.push).not.toHaveBeenCalled()
  })

  it("asks for a file on the Media tab", async () => {
    const user = userEvent.setup()
    renderWithIntl(<SubmissionComposer />)
    await user.click(screen.getAllByRole("tab")[2])
    await user.click(submitButton())
    await waitFor(() => expect(screen.getByRole("form").querySelector("[aria-invalid='true'], #submit-file-error")).not.toBeNull())
    expect(router.push).not.toHaveBeenCalled()
  })
})
