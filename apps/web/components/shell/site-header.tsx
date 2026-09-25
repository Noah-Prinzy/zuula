"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { RiArrowLeftLine } from "@remixicon/react"
import { useTranslations } from "next-intl"

import { useSession } from "@/components/providers/session-provider"
import { GlobalSearch } from "@/components/shell/global-search"
import { LanguageSwitcher } from "@/components/shell/language-switcher"
import { Logo } from "@/components/shell/logo"
import { NotificationBell } from "@/components/shell/notification-bell"
import { ThemeToggle } from "@/components/shell/theme-toggle"
import { UserMenu } from "@/components/shell/user-menu"
import { Button } from "@/components/ui/button"
import { isInSection, NON_PAGE_ROUTES, PUBLIC_NAV } from "@/lib/navigation"
import { hasAnyRole } from "@/lib/roles"
import { cn } from "@/lib/utils"
import { canGoBackInApp, useTrackInAppHistory } from "@/hooks/use-in-app-history"
import { usePagePath } from "@/hooks/use-page-path"

// The pages the phone tab bar leads to. Every other page is a screen pushed on top of one of
// them, so on phones the header swaps the logo for a back button and the page's title.
const TAB_ROOTS = new Set(["/", "/verify", "/fact-checks", "/offline"])

// On phones the header is a compact app bar: the logo (or back and title) and search. The
// links, language, theme and account menus live in the tab bar and its account sheet instead.
export function SiteHeader() {
  const pathname = usePagePath()
  const { user, role } = useSession()
  const t = useTranslations("Nav")

  const nav = PUBLIC_NAV.filter((item) => hasAnyRole(role, item.roles))
  const pushed = !TAB_ROOTS.has(pathname)
  useTrackInAppHistory(pathname)

  return (
    <header className="sticky top-0 z-40 border-b bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/70">
      <div className="page-container flex h-14 items-center gap-2 md:gap-4">
        {pushed && <MobileBack pathname={pathname} />}
        <Logo className={cn(pushed && "max-md:hidden")} />

        <nav
          aria-label={t("main")}
          // Longer labels (translations) scroll inside the bar rather than widening the page.
          className="hidden min-w-0 items-stretch gap-1 self-stretch overflow-x-auto [scrollbar-width:none] md:flex"
        >
          {nav.map((item) => {
            const active = isInSection(pathname, item.href)
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "press flex shrink-0 items-center px-2.5 text-sm whitespace-nowrap text-muted-foreground [--press-tint:transparent] hover:text-foreground",
                  active && "text-foreground underline decoration-primary decoration-2 underline-offset-[18px]"
                )}
              >
                {t(`items.${item.key}`)}
              </Link>
            )
          })}
        </nav>

        <div className="ml-auto flex shrink-0 items-center gap-1">
          <GlobalSearch />
          <div className="hidden items-center gap-1 md:flex">
            <LanguageSwitcher />
            <ThemeToggle />
          </div>
          {user && <NotificationBell />}
          <div className="hidden md:block">
            <UserMenu />
          </div>
        </div>
      </div>
    </header>
  )
}

// Where "back" goes when there is no in-app history to return to (the page was opened from a
// link or a refresh): the parent path, skipping segments with no page of their own.
function parentOf(pathname: string) {
  let parent = pathname
  do parent = parent.slice(0, parent.lastIndexOf("/")) || "/"
  while (NON_PAGE_ROUTES.has(parent))
  return parent
}

function MobileBack({ pathname }: { pathname: string }) {
  const router = useRouter()
  const t = useTranslations("Nav")
  const title = usePageTitle(pathname)

  return (
    <div className="flex min-w-0 flex-1 items-center gap-1 md:hidden">
      <Button
        variant="ghost"
        size="icon"
        className="-ml-2 size-11 shrink-0 [&_svg:not([class*='size-'])]:size-5"
        aria-label={t("back")}
        onClick={() => (canGoBackInApp() ? router.back() : router.push(parentOf(pathname)))}
      >
        <RiArrowLeftLine aria-hidden />
      </Button>
      {/* The page's own heading, shown here once it has scrolled under the bar. */}
      <p
        aria-hidden
        className={cn(
          "min-w-0 truncate font-heading text-base font-semibold transition-opacity duration-200",
          title.visible ? "opacity-100" : "opacity-0"
        )}
      >
        {title.text}
      </p>
    </div>
  )
}

// Tracks the page's h1: its text, and whether it has scrolled up under the header.
function usePageTitle(pathname: string) {
  const [title, setTitle] = useState({ text: "", visible: false })

  useEffect(() => {
    const main = document.getElementById("main")
    if (!main) return
    let observed: Element | null = null
    const io = new IntersectionObserver(
      ([e]) => setTitle((s) => ({ ...s, visible: !e.isIntersecting && e.boundingClientRect.top < 0 })),
      { rootMargin: "-56px 0px 0px 0px" }
    )
    const track = () => {
      const h1 = main.querySelector("h1")
      if (h1 === observed) {
        if (h1) setTitle((s) => (s.text === h1.textContent ? s : { ...s, text: h1.textContent ?? "" }))
        return
      }
      if (observed) io.unobserve(observed)
      observed = h1
      setTitle({ text: h1?.textContent ?? "", visible: false })
      if (h1) io.observe(h1)
    }
    track()
    // Pages that load their content after the first render put their heading in later.
    const mo = new MutationObserver(track)
    mo.observe(main, { childList: true, subtree: true })
    return () => {
      mo.disconnect()
      io.disconnect()
    }
  }, [pathname])

  return title
}
