// @vitest-environment jsdom
import { render } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

const setTheme = vi.hoisted(() => vi.fn())
vi.mock("next-themes", () => ({
  ThemeProvider: ({ children }: { children: React.ReactNode }) => children,
  useTheme: () => ({ resolvedTheme: "light", setTheme }),
}))

import { ThemeProvider } from "@/components/theme-provider"

describe("the D theme shortcut", () => {
  it("ignores keydown events with no key, as Chrome sends when autofilling a password", () => {
    render(<ThemeProvider>page</ThemeProvider>)
    expect(() => window.dispatchEvent(new Event("keydown"))).not.toThrow()
    expect(setTheme).not.toHaveBeenCalled()
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "d" }))
    expect(setTheme).toHaveBeenCalledWith("dark")
  })
})
