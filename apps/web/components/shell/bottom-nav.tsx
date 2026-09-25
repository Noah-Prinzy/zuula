"use client"

import { useState } from "react"
import Link from "next/link"
import {
  RiBookmarkFill,
  RiBookmarkLine,
  RiBookOpenFill,
  RiBookOpenLine,
  RiHome5Fill,
  RiHome5Line,
  RiSearchEyeFill,
  RiSearchEyeLine,
  RiUser3Fill,
  RiUser3Line,
  RiWifiOffLine,
  type RemixiconComponentType,
} from "@remixicon/react"
import { useTranslations } from "next-intl"

import { useNotifications } from "@/components/account/notifications-store"
import { useSession } from "@/components/providers/session-provider"
import { useOnline } from "@/components/pwa/use-online"
import { isInSection } from "@/lib/navigation"
import { cn, initials } from "@/lib/utils"
import { usePagePath } from "@/hooks/use-page-path"

import { AccountSheet } from "./account-sheet"

type Tab = {
  href: string
  label: string
  icon: RemixiconComponentType
  activeIcon: RemixiconComponentType
  active: boolean
}

// Where the account tab lights up: every page reached from its sheet.
const SHEET_SECTIONS = ["/account", "/review", "/admin", "/about", "/developers", "/legal"]

// Phone tab bar (below md, where the header drops its links): Home, the Library, Saved (the
// offline reading list, one tap away on a poor connection) and the account sheet, with Verify,
// the app's main action, as a raised button in the middle, in the thumb's natural reach.
// The account tab opens a bottom sheet (account-sheet.tsx) holding everything the desktop
// header keeps in menus, so phones need no hamburger. A spacer in the page flow keeps the last
// content clear of the bar; its height is --bottom-nav-h (globals.css), which also clears the
// home indicator.
// Offline, a strip on top of the bar says so and points to the saved reports. A live region
// that is always mounted (and not limited to phones) announces going offline and back online;
// screen readers often skip live regions that appear already filled.
export function BottomNav() {
  const pathname = usePagePath()
  const { user } = useSession()
  const { unread } = useNotifications()
  const t = useTranslations("Nav")
  const to = useTranslations("Offline")
  const online = useOnline()
  const [sheetOpen, setSheetOpen] = useState(false)
  // Remember an outage so the live region can also announce the reconnection.
  const [wasOffline, setWasOffline] = useState(false)
  if (!online && !wasOffline) setWasOffline(true)

  // Screens with a bottom bar of their own (a report's actions) take the tab bar's place.
  const ownBar = /^\/fact-checks\/[^/]+$/.test(pathname)
  const verifyActive = isInSection(pathname, "/verify") || pathname.startsWith("/submissions/")
  const sheetActive = SHEET_SECTIONS.some((s) => isInSection(pathname, s))
  const tab = (href: string, label: string, icon: RemixiconComponentType, activeIcon: RemixiconComponentType, active: boolean): Tab => ({
    href,
    label,
    icon,
    activeIcon,
    active,
  })
  const left = [
    tab("/", t("items.home"), RiHome5Line, RiHome5Fill, pathname === "/"),
    tab("/fact-checks", t("items.library"), RiBookOpenLine, RiBookOpenFill, isInSection(pathname, "/fact-checks")),
  ]
  const right = [tab("/offline", t("items.saved"), RiBookmarkLine, RiBookmarkFill, isInSection(pathname, "/offline"))]

  return (
    <>
      <p role="status" className="sr-only">
        {!online ? to("banner") : wasOffline ? to("bannerBack") : ""}
      </p>
      <div aria-hidden className={cn("h-(--bottom-nav-h) shrink-0 md:hidden", !online && "h-[calc(var(--bottom-nav-h)+2rem)]")} />
      <nav
        aria-label={t("tabBar")}
        hidden={ownBar}
        className="fixed inset-x-0 bottom-0 z-40 border-t bg-background pb-[env(safe-area-inset-bottom)] md:hidden"
      >
        {!online && (
          <p className="flex h-8 items-center justify-between gap-3 border-b bg-muted px-4 text-xs">
            <span className="inline-flex items-center gap-1.5 font-medium">
              <RiWifiOffLine className="size-3.5" aria-hidden />
              {to("banner")}
            </span>
            {!isInSection(pathname, "/offline") && (
              <Link href="/offline" className="font-medium underline underline-offset-4">
                {to("bannerAction")}
              </Link>
            )}
          </p>
        )}
        <ul className="grid h-14 grid-cols-5">
          {left.map((tab) => (
            <TabLink key={tab.href} {...tab} />
          ))}
          <li className="flex min-w-0 *:min-w-0">
            <Link
              href="/verify"
              aria-current={verifyActive ? "page" : undefined}
              className="group/verify relative flex flex-1 flex-col items-center justify-center gap-0.5 text-[0.6875rem] font-semibold text-foreground outline-none"
            >
              {/* Raised above the bar's top edge, square like the rest of the preset. */}
              <span
                className={cn(
                  "press absolute -top-5 left-1/2 flex size-12 -translate-x-1/2 items-center justify-center bg-primary text-primary-foreground shadow-md ring-4 ring-background transition-colors",
                  "group-focus-visible/verify:outline-2 group-focus-visible/verify:outline-offset-4 group-focus-visible/verify:outline-ring",
                  "group-active/verify:scale-95 motion-reduce:group-active/verify:scale-100"
                )}
              >
                {verifyActive ? <RiSearchEyeFill className="size-6" aria-hidden /> : <RiSearchEyeLine className="size-6" aria-hidden />}
              </span>
              {/* Holds the icon's place, so the label lines up with the other tabs'. */}
              <span aria-hidden className="size-5" />
              <span className={cn("max-w-full truncate px-1", verifyActive && "text-primary")}>{t("items.verify")}</span>
            </Link>
          </li>
          {right.map((tab) => (
            <TabLink key={tab.href} {...tab} />
          ))}
          <li className="flex min-w-0 *:min-w-0">
            <button
              type="button"
              onClick={() => setSheetOpen(true)}
              aria-haspopup="dialog"
              aria-expanded={sheetOpen}
              aria-label={user && unread > 0 ? `${t("groups.account")} (${unread})` : undefined}
              className={cn(
                tabClass,
                sheetActive && "font-semibold text-foreground before:bg-primary"
              )}
            >
              {user ? (
                <span
                  aria-hidden
                  className={cn(
                    "relative flex size-6 items-center justify-center rounded-full bg-muted text-[0.625rem] font-semibold text-foreground",
                    sheetActive && "bg-primary text-primary-foreground"
                  )}
                >
                  {initials(user.name)}
                  {unread > 0 && (
                    <span className="absolute -top-0.5 -right-0.5 size-2 rounded-full bg-primary ring-2 ring-background dark:bg-destructive" />
                  )}
                </span>
              ) : sheetActive ? (
                <RiUser3Fill className="size-5 text-primary" aria-hidden />
              ) : (
                <RiUser3Line className="size-5" aria-hidden />
              )}
              <span className="max-w-full truncate px-1">{t("groups.account")}</span>
            </button>
          </li>
        </ul>
      </nav>
      <AccountSheet open={sheetOpen} onOpenChange={setSheetOpen} />
    </>
  )
}

const tabClass = cn(
  "press-tint relative flex flex-1 flex-col items-center justify-center gap-0.5 text-[0.6875rem] text-muted-foreground transition-colors outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset",
  // Same 2px primary marker as the header links and section tabs.
  "before:absolute before:inset-x-3 before:top-0 before:h-0.5 before:bg-transparent before:transition-colors"
)

function TabLink({ href, label, icon, activeIcon, active }: Tab) {
  const Icon = active ? activeIcon : icon
  return (
    <li className="flex min-w-0 *:min-w-0">
      <Link
        href={href}
        aria-current={active ? "page" : undefined}
        className={cn(tabClass, active && "font-semibold text-foreground before:bg-primary")}
      >
        <Icon className={cn("size-5", active && "text-primary")} aria-hidden />
        <span className="max-w-full truncate px-1">{label}</span>
      </Link>
    </li>
  )
}
