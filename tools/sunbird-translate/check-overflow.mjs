// Loads every page of a running apps/web build in each language at phone, tablet and desktop
// widths, and reports text that spills out of its box: horizontal page scroll, text wider or
// taller than its element, elements pushed off-screen, and text cut off by a clipping parent.
// Issues are grouped by whether they also happen in English (pre-existing) or only in a
// translation (caused by longer text).
//
//   BASE=http://localhost:3000 node check-overflow.mjs [--locales=lg,ach] [--routes=/,/verify]
import fs from "node:fs"
import { createRequire } from "node:module"

// Playwright is not an apps/web dependency: install it anywhere and point NODE_PATH at it.
const require = createRequire(import.meta.url)
const { chromium } = require("playwright")

const BASE = process.env.BASE || "http://localhost:3000"
const args = Object.fromEntries(process.argv.slice(2).map((a) => a.replace(/^--/, "").split("=")))
const LOCALES = ["en", ...(args.locales ? args.locales.split(",") : ["lg", "ach", "nyn", "teo"])]
const WIDTHS = [360, 768, 1280]
const ROUTES = args.routes
  ? args.routes.split(",")
  : [
      "/", "/verify", "/fact-checks", "/fact-checks/fc-2026-0142", "/about", "/developers",
      "/legal/privacy", "/legal/terms", "/offline", "/sign-in", "/sign-in/two-factor", "/sign-up",
      "/sign-up/verify", "/forgot-password", "/reset-password", "/account", "/account/activity",
      "/account/alerts", "/account/api-access", "/account/notifications", "/account/verification",
      "/review", "/review/queue", "/review/history", "/review/cases/rc-0418", "/admin",
      "/admin/users", "/admin/moderation", "/admin/sources", "/admin/broadcasts", "/admin/reports",
      "/admin/audit-log", "/admin/configuration", "/no-such-page",
    ]
const SESSION = { id: "demo-admin", name: "Mary Akello", email: "admin@zuula.ug", role: "admin", twoFactorEnabled: true }

function scan() {
  const vw = window.innerWidth
  const out = []
  const path = (el) => {
    const parts = []
    for (let e = el; e && e !== document.body && parts.length < 4; e = e.parentElement) {
      const cls = [...e.classList].filter((c) => !c.includes("[") || c.length < 40).slice(0, 4).join(".")
      parts.unshift(e.tagName.toLowerCase() + (cls ? "." + cls : ""))
    }
    return parts.join(" > ")
  }
  const text = (el) => (el.innerText || "").trim().replace(/\s+/g, " ").slice(0, 60)
  if (document.documentElement.scrollWidth > vw + 1)
    out.push({ kind: "page-hscroll", where: "document", text: `${document.documentElement.scrollWidth}px > ${vw}px` })
  // Scroll containers (rails, tables, code blocks) are meant to hold content wider than
  // themselves; anything inside one is reachable by scrolling, so it isn't a leak.
  const insideScroller = (el) => {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement)
      if (/auto|scroll/.test(getComputedStyle(p).overflowX)) return true
    return false
  }
  for (const el of document.body.querySelectorAll("*")) {
    const cs = getComputedStyle(el)
    if (cs.display === "none" || cs.visibility === "hidden" || cs.display === "contents") continue
    // Visually hidden on purpose: sr-only text and decorative (aria-hidden) subtrees.
    if (el.closest(".sr-only, [aria-hidden=true]") || cs.clip === "rect(0px, 0px, 0px, 0px)") continue
    const r = el.getBoundingClientRect()
    if (r.width <= 1 || r.height <= 1) continue // sr-only and collapsed
    // Fully hidden by a clipping ancestor (the next slide of a carousel): not visible at all.
    let clippedAway = false
    for (let p = el.parentElement; p && p !== document.body && !clippedAway; p = p.parentElement) {
      if (!/hidden|clip/.test(getComputedStyle(p).overflowX)) continue
      const pr = p.getBoundingClientRect()
      clippedAway = r.left >= pr.right || r.right <= pr.left
    }
    if (clippedAway) continue
    const ownText = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())
    if (!ownText) continue
    const inline = cs.display === "inline"
    const scrollable = /auto|scroll/.test(cs.overflowX + cs.overflowY)
    if (!inline && !scrollable) {
      if (el.scrollWidth > el.clientWidth + 1) {
        const kind = cs.textOverflow === "ellipsis" ? "truncated" : "text-wider-than-box"
        out.push({ kind, where: path(el), text: text(el), px: el.scrollWidth - el.clientWidth })
      }
      // Only fixed or max heights can be exceeded; line-clamped text is cut off on purpose.
      if (el.scrollHeight > el.clientHeight + 4 && (cs.webkitLineClamp || "none") === "none")
        out.push({ kind: "text-taller-than-box", where: path(el), text: text(el), px: el.scrollHeight - el.clientHeight })
    }
    // Entirely outside the screen means parked on purpose (a carousel slide, a closed drawer);
    // a leak is text that is partly visible and runs past the edge.
    const parked = r.left >= vw || r.right <= 0
    if ((r.right > vw + 1 || r.left < -1) && !parked && !insideScroller(el)) {
      // Ignore things deliberately parked off-screen (skip links, closed drawers).
      if (cs.position !== "fixed" && cs.position !== "absolute")
        out.push({ kind: "off-screen", where: path(el), text: text(el), px: Math.round(Math.max(r.right - vw, -r.left)) })
    }
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const pcs = getComputedStyle(p)
      if (/auto|scroll/.test(pcs.overflowX)) break
      if (/hidden|clip/.test(pcs.overflowX)) {
        // Truncation with an ellipsis or a line clamp is the design, not a leak.
        if (pcs.textOverflow === "ellipsis" || (pcs.webkitLineClamp || "none") !== "none") break
        const pr = p.getBoundingClientRect()
        const hidden = r.left >= pr.right || r.right <= pr.left
        if (!hidden && (r.right > pr.right + 1 || r.left < pr.left - 1))
          out.push({ kind: "clipped-by-parent", where: path(el), text: text(el), px: Math.round(Math.max(r.right - pr.right, pr.left - r.left)) })
        break
      }
    }
  }
  return out
}

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || "/opt/pw-browsers/chromium" }).catch(() => chromium.launch())
const results = {}
for (const locale of LOCALES) {
  for (const width of WIDTHS) {
    const ctx = await browser.newContext({ viewport: { width, height: 900 } })
    await ctx.addCookies([{ name: "NEXT_LOCALE", value: locale, url: BASE }])
    await ctx.addInitScript((s) => localStorage.setItem("zuula.demo-session", JSON.stringify(s)), SESSION)
    const page = await ctx.newPage()
    for (const route of ROUTES) {
      try {
        await page.goto(BASE + route, { waitUntil: "networkidle", timeout: 60000 })
        await page.waitForTimeout(300)
        results[`${locale}|${width}|${route}`] = await page.evaluate(scan)
      } catch (e) {
        results[`${locale}|${width}|${route}`] = [{ kind: "load-error", where: route, text: e.message.slice(0, 120) }]
      }
    }
    await ctx.close()
  }
  process.stderr.write(`scanned ${locale}\n`)
}
await browser.close()

// Compare with English: the same kind at the same element on the same page/width is pre-existing.
// A translation issue counts as pre-existing only if English overflows the same element by
// about as much; overflowing more than 8px further is caused by the longer text.
const sig = (i) => `${i.kind}|${i.where}`
const report = { onlyInTranslation: [], alsoInEnglish: [] }
for (const [key, issues] of Object.entries(results)) {
  const [locale, width, route] = key.split("|")
  if (locale === "en") continue
  const en = new Map((results[`en|${width}|${route}`] || []).map((i) => [sig(i), i.px ?? 0]))
  for (const i of issues) {
    if (i.kind === "truncated") continue // deliberate ellipsis
    const pre = en.has(sig(i)) && (i.px ?? 0) <= en.get(sig(i)) + 8
    ;(pre ? report.alsoInEnglish : report.onlyInTranslation).push({ locale, width: Number(width), route, ...i })
  }
}
for (const [key, issues] of Object.entries(results))
  if (key.startsWith("en|"))
    for (const i of issues) if (i.kind !== "truncated") report.alsoInEnglish.push({ locale: "en", width: Number(key.split("|")[1]), route: key.split("|")[2], ...i })
fs.writeFileSync(new URL("./overflow-report.json", import.meta.url), JSON.stringify(report, null, 2))
const count = (list) => list.reduce((m, i) => ((m[i.kind] = (m[i.kind] || 0) + 1), m), {})
console.log("only in translation:", report.onlyInTranslation.length, count(report.onlyInTranslation))
console.log("also in English:", report.alsoInEnglish.filter((i) => i.locale === "en").length, count(report.alsoInEnglish.filter((i) => i.locale === "en")))
process.exit(report.onlyInTranslation.length ? 1 : 0)
