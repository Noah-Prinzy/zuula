import {
  RiAwardLine,
  RiDashboardLine,
  RiFileList3Line,
  RiFileSearchLine,
  RiGroupLine,
  RiHistoryLine,
  RiKey2Line,
  RiMegaphoneLine,
  RiNotification3Line,
  RiNotificationBadgeLine,
  RiPieChartLine,
  RiSettings3Line,
  RiShieldCheckLine,
  RiShieldUserLine,
  RiSlideshowLine,
  RiTimeLine,
  RiUserSettingsLine,
  RiVerifiedBadgeLine,
  type RemixiconComponentType,
} from "@remixicon/react"

import type en from "@/messages/en.json"
import type { Role } from "@/lib/roles"

// Translation keys under Nav.items / Nav.groups (messages/*.json).
export type NavItemKey = keyof (typeof en)["Nav"]["items"]
export type NavGroupKey = keyof (typeof en)["Nav"]["groups"]

export type NavItem = {
  key: NavItemKey
  /** English label, used where no translator is available (e.g. metadata). */
  title: string
  href: string
  icon?: RemixiconComponentType
  roles?: readonly Role[]
}

export type NavGroup = {
  key: NavGroupKey
  label: string
  href: string
  items: NavItem[]
  roles?: readonly Role[]
}

export const REVIEWERS = ["expert", "admin"] as const
export const ADMINS = ["admin"] as const

export const PUBLIC_NAV: NavItem[] = [
  { key: "verify", title: "Verify", href: "/verify" },
  { key: "library", title: "Library", href: "/fact-checks" },
  { key: "about", title: "About", href: "/about" },
  { key: "review", title: "Review", href: "/review", roles: REVIEWERS },
  { key: "admin", title: "Admin", href: "/admin", roles: ADMINS },
]

export const APP_NAV: NavGroup[] = [
  {
    key: "review",
    label: "Review",
    href: "/review",
    roles: REVIEWERS,
    items: [
      { key: "reviewOverview", title: "Overview", href: "/review", icon: RiDashboardLine },
      { key: "reviewQueue", title: "Queue", href: "/review/queue", icon: RiShieldCheckLine },
      { key: "reviewHistory", title: "History", href: "/review/history", icon: RiHistoryLine },
    ],
  },
  {
    key: "admin",
    label: "Admin",
    href: "/admin",
    roles: ADMINS,
    items: [
      { key: "adminOverview", title: "Overview", href: "/admin", icon: RiPieChartLine },
      { key: "adminUsers", title: "Users", href: "/admin/users", icon: RiGroupLine },
      { key: "adminVerifications", title: "Verifications", href: "/admin/verifications", icon: RiVerifiedBadgeLine },
      { key: "adminModeration", title: "Moderation", href: "/admin/moderation", icon: RiFileSearchLine },
      { key: "adminSources", title: "Sources", href: "/admin/sources", icon: RiFileList3Line },
      { key: "adminBroadcasts", title: "Broadcasts", href: "/admin/broadcasts", icon: RiMegaphoneLine },
      { key: "adminReports", title: "Reports", href: "/admin/reports", icon: RiSlideshowLine },
      { key: "adminAuditLog", title: "Audit Log", href: "/admin/audit-log", icon: RiShieldUserLine },
      { key: "adminSettings", title: "Settings", href: "/admin/configuration", icon: RiSettings3Line },
    ],
  },
  {
    key: "account",
    label: "Account",
    href: "/account",
    items: [
      { key: "profile", title: "Profile", href: "/account", icon: RiUserSettingsLine },
      { key: "activity", title: "Activity", href: "/account/activity", icon: RiTimeLine },
      { key: "notifications", title: "Notifications", href: "/account/notifications", icon: RiNotificationBadgeLine },
      { key: "alerts", title: "Alerts", href: "/account/alerts", icon: RiNotification3Line },
      {
        key: "accreditation",
        title: "Accreditation",
        href: "/account/verification",
        icon: RiAwardLine,
        roles: ["public", "journalist"],
      },
      {
        key: "apiKeys",
        title: "API Keys",
        href: "/account/api-access",
        icon: RiKey2Line,
        roles: ["journalist", "admin"],
      },
    ],
  },
]

const SECTION_ROOTS = APP_NAV.map((g) => g.href)

// Breadcrumb labels. Section roots show the section name, not the page name.
export const ROUTE_TITLES: Record<string, string> = Object.fromEntries([
  ...APP_NAV.flatMap((g) => g.items.map((i) => [i.href, i.title])),
  ...APP_NAV.map((g) => [g.href, g.label]),
  ["/review/cases", "Cases"],
])

// Same, as translation keys: [href, "items.x" | "groups.x"].
export const ROUTE_KEYS: Record<string, `items.${NavItemKey}` | `groups.${NavGroupKey}`> = Object.fromEntries([
  ...APP_NAV.flatMap((g) => g.items.map((i) => [i.href, `items.${i.key}`])),
  ...APP_NAV.map((g) => [g.href, `groups.${g.key}`]),
  ["/review/cases", "items.reviewCases"],
])

// Path segments that exist only as URL structure, with no page of their own.
export const NON_PAGE_ROUTES = new Set(["/review/cases"])

// Pages without a nav item of their own highlight their parent's item instead.
const ACTIVE_ALIASES: [prefix: string, href: string][] = [["/review/cases", "/review/queue"]]

export function isActivePath(pathname: string, href: string) {
  if (href === "/") return pathname === "/"
  const alias = ACTIVE_ALIASES.find(([prefix]) => pathname.startsWith(prefix))
  if (alias) return alias[1] === href
  // Section roots only match exactly inside the section nav.
  if (SECTION_ROOTS.includes(href)) return pathname === href
  return pathname === href || pathname.startsWith(`${href}/`)
}

// Header links highlight for anything under their section.
export function isInSection(pathname: string, href: string) {
  return pathname === href || pathname.startsWith(`${href}/`)
}
