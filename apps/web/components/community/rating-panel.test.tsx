// @vitest-environment jsdom
import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import type { Role } from "@/lib/roles"
import { counts } from "@/test/fixtures"
import { renderWithIntl } from "@/test/render"

const session = vi.hoisted(() => ({ role: null as Role | null }))
vi.mock("@/components/providers/session-provider", () => ({
  useSession: () => ({
    role: session.role,
    user: session.role ? { name: "Test User", email: "t@example.com", role: session.role } : null,
  }),
}))
vi.mock("next/navigation", () => ({
  usePathname: () => "/fact-checks/fc-1",
  useRouter: () => ({ refresh: vi.fn() }),
}))
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
vi.mock("sonner", () => ({ toast }))
// No backend configured in these tests: every assertion below is the same local-only,
// optimistic-UI behavior the panel had before the real ratings API existed.
vi.mock("@/lib/ratings-api", () => ({
  ratingsApiConfigured: () => false,
  rate: vi.fn(),
  retractRating: vi.fn(),
  addComment: vi.fn(),
}))
vi.mock("@/lib/fact-checks-api", () => ({ fetchFullReport: vi.fn() }))

import { RatingPanel } from "@/components/community/rating-panel"

// 3 public say accurate, 1 says inaccurate → 75%.
const initial = { accurate: counts({ public: 3 }), inaccurate: counts({ public: 1 }) }
const reportId = "fc-1"
const score = () => screen.getByText(/^\d+%$|^—$/).textContent

beforeEach(() => {
  session.role = null
  toast.success.mockClear()
})

describe("RatingPanel", () => {
  it("shows the community score", () => {
    renderWithIntl(<RatingPanel reportId={reportId} initial={initial} />)
    expect(score()).toBe("75%")
  })

  it("asks signed-out visitors to sign in and disables voting", () => {
    renderWithIntl(<RatingPanel reportId={reportId} initial={initial} />)
    const group = screen.getByRole("group")
    for (const button of within(group).getAllByRole("button")) expect(button).toBeDisabled()
    expect(screen.getByRole("link", { name: /sign in/i })).toHaveAttribute(
      "href",
      "/sign-in?next=%2Ffact-checks%2Ffc-1"
    )
  })

  it("tells signed-in users how much their rating counts", () => {
    session.role = "expert"
    renderWithIntl(<RatingPanel reportId={reportId} initial={initial} />)
    expect(screen.getByText(/5×/)).toBeInTheDocument()
  })

  it("records a vote, weights it by role and lets the user change it", async () => {
    session.role = "journalist"
    const user = userEvent.setup()
    renderWithIntl(<RatingPanel reportId={reportId} initial={initial} />)
    const [accurate, inaccurate] = within(screen.getByRole("group")).getAllByRole("button")

    await user.click(accurate)
    expect(accurate).toHaveAttribute("aria-pressed", "true")
    // (3 + 2) / (3 + 2 + 1) = 83%
    expect(score()).toBe("83%")
    expect(toast.success).toHaveBeenCalledTimes(1)

    await user.click(inaccurate)
    expect(inaccurate).toHaveAttribute("aria-pressed", "true")
    expect(accurate).toHaveAttribute("aria-pressed", "false")
    // 3 / (3 + 1 + 2) = 50%
    expect(score()).toBe("50%")

    // Clicking the same choice again is a no-op.
    await user.click(inaccurate)
    expect(toast.success).toHaveBeenCalledTimes(2)
  })

  it("saves an optional reason", async () => {
    session.role = "public"
    const user = userEvent.setup()
    renderWithIntl(<RatingPanel reportId={reportId} initial={initial} />)

    await user.click(within(screen.getByRole("group")).getAllByRole("button")[0])
    await user.click(screen.getByRole("button", { name: /add a reason/i }))
    const dialog = await screen.findByRole("dialog")
    await user.type(within(dialog).getByRole("textbox"), "  Checked the ministry statement  ")
    await user.click(within(dialog).getByRole("button", { name: /save/i }))

    expect(await screen.findByText(/Checked the ministry statement/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /edit reason/i })).toBeInTheDocument()
  })
})
