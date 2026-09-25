// Machine-draft apps/web/messages/{lg,ach,nyn,teo}.json from en.json via Sunbird /tasks/translate.
// ICU syntax never reaches the model: messages are parsed with the same parser next-intl's
// intl-messageformat uses, plural/select are hoisted so each option is a whole sentence,
// arguments / `#` / verbatim tags / protected terms become opaque {N} markers, and the
// result is rebuilt as an AST, printed, re-parsed and structurally compared with English.
import fs from "node:fs"
import path from "node:path"
import { createRequire } from "node:module"

const WEB = new URL("../../apps/web", import.meta.url).pathname
const require = createRequire(WEB + "/package.json")
const { parse } = require(WEB + "/node_modules/intl-messageformat/node_modules/@formatjs/icu-messageformat-parser")
const { printAST } = require(WEB + "/node_modules/@formatjs/icu-messageformat-parser/printer.js")
const { IntlMessageFormat } = require(WEB + "/node_modules/intl-messageformat")

const HERE = path.dirname(new URL(import.meta.url).pathname)
const FAKE = !!process.env.FAKE
const CACHE = path.join(HERE, FAKE ? "fake-cache.jsonl" : "cache.jsonl")
const OUTDIR = FAKE ? path.join(HERE, "fake-out") : path.join(WEB, "messages")
const REPORT = path.join(HERE, FAKE ? "fake-report.json" : "report.json")
const LANGS = { lg: "lug", ach: "ach", nyn: "nyn", teo: "teo" }
const T = { literal: 0, argument: 1, number: 2, date: 3, time: 4, select: 5, plural: 6, pound: 7, tag: 8 }

// Tags whose content is code, an address or only an argument: kept verbatim.
const VERBATIM_TAGS = new Set(["code", "email", "q", "time"])
// Keys deliberately left in English because they're the same in every language: the brand
// name, and the search keyboard shortcut (the model "translated" Ctrl K into a question).
const SKIP = [/^Common\.appName$/, /^Search\.shortcut$/]
const PROTECT = new RegExp(
  [
    String.raw`https?://\S+`,
    String.raw`[\w.+-]+@[\w-]+(?:\.[\w-]+)+`,
    String.raw`\bzuula\.ug\b`,
    String.raw`(?<!\w)/[\w.\-\[\]]+(?:/[\w.\-\[\]]+)+`,
    String.raw`\b(?:Zuula|Sunbird(?: AI)?|WhatsApp|Facebook|TikTok|YouTube|Instagram|Telegram|Google|Twitter|WebP|WebM)\b`,
    String.raw`\b(?=[A-Z0-9_.-]*[A-Z][A-Z0-9_.-]*[A-Z0-9])[A-Z0-9]+(?:[-_.][A-Z0-9]+)*\b`,
    String.raw`\d[\d,.:]*\d|\d`,
  ].join("|"),
  "g",
)

// ---------- AST helpers ----------
const clone = (x) => JSON.parse(JSON.stringify(x))
const strip = (x) => JSON.parse(JSON.stringify(x, (k, v) => (k === "location" ? undefined : v)))
const isChoice = (el) => el.type === T.select || el.type === T.plural
const hasPound = (seq) => seq.some((e) => e.type === T.pound || (e.type === T.tag && hasPound(e.children)))

class Fail extends Error {}

// Hoist plural/select so that each option holds a complete sentence. Selects go outermost:
// moving a `#` into a nested select would change its meaning, so two plurals that would
// need that are refused (the key is then left to English fallback).
function hoist(seq) {
  seq = seq.map((e) => (e.type === T.tag ? { ...e, children: hoist(e.children) } : e))
  const choices = seq.map((e, i) => [e, i]).filter(([e]) => isChoice(e))
  if (!choices.length) return seq
  const [el, i] = choices.find(([e]) => e.type === T.select) || choices[0]
  const prefix = seq.slice(0, i), suffix = seq.slice(i + 1)
  // A top-level `#` belongs to the enclosing plural; moving it into this choice would rebind it.
  if (hasPound(prefix) || hasPound(suffix)) throw new Fail("# would move into a nested choice")
  const out = clone(el)
  for (const k of Object.keys(out.options))
    out.options[k].value = hoist([...clone(prefix), ...clone(el.options[k].value), ...clone(suffix)])
  return [out]
}

// Walk a hoisted sequence, calling `unit(text, markers)` for each translatable run.
// `unit` returns the translated text or throws Fail. Returns a new AST.
function build(seq, unit) {
  if (seq.length === 1 && isChoice(seq[0])) {
    const out = clone(seq[0])
    for (const k of Object.keys(out.options)) out.options[k].value = build(seq[0].options[k].value, unit)
    return [out]
  }
  let text = ""
  const markers = []
  const mark = (node) => {
    text += `{${markers.length}}`
    markers.push(node)
  }
  for (const el of seq) {
    if (el.type === T.literal) {
      let last = 0
      for (const m of el.value.matchAll(PROTECT)) {
        text += el.value.slice(last, m.index)
        mark({ type: T.literal, value: m[0] })
        last = m.index + m[0].length
      }
      text += el.value.slice(last)
    } else if (el.type === T.tag) {
      mark(VERBATIM_TAGS.has(el.value) ? el : { ...el, children: build(el.children, unit) })
    } else if (isChoice(el)) {
      throw new Fail("choice inside a run")
    } else if (el.type === T.pound) {
      mark(el)
    } else {
      mark(el)
    }
  }
  if (!/\p{L}{2,}/u.test(text.replace(/\{\d+\}/g, ""))) {
    return markers.length === 0 ? seq : restore(text, markers)
  }
  const lead = text.match(/^\s*/)[0], trail = text.match(/\s*$/)[0]
  const core = text.trim()
  const translated = unit(core, markers.length)
  return restore(lead + translated + trail, markers)
}

function restore(text, markers) {
  const out = []
  let last = 0
  const lit = (s) => {
    if (!s) return
    const prev = out[out.length - 1]
    if (prev && prev.type === T.literal) prev.value += s
    else out.push({ type: T.literal, value: s })
  }
  for (const m of text.matchAll(/\{(\d+)\}/g)) {
    lit(text.slice(last, m.index))
    const node = markers[Number(m[1])]
    if (node.type === T.literal) lit(node.value)
    else out.push(clone(node))
    last = m.index + m[0].length
  }
  lit(text.slice(last))
  return out
}


// ICU serializer that keeps English's option order and style. Apostrophes are doubled only
// where ICU would read them as quote syntax (before { } < > # | ' or at the end of a literal).
function esc(text, inPlural) {
  let out = ""
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (c === "'") {
      const nxt = i + 1 < text.length ? text[i + 1] : "{" // end of a literal: syntax or end of string follows
      out += nxt && "'{}<>#|".includes(nxt) ? "''" : "'"
    } else if ("{}<".includes(c) || (c === "#" && inPlural)) out += `'${c}'`
    else out += c
  }
  return out
}
function serialize(ast, inPlural = false) {
  return ast
    .map((el, i) => {
      switch (el.type) {
        case T.literal: return esc(el.value, inPlural)
        case T.argument: return `{${el.value}}`
        case T.number: case T.date: case T.time: {
          if (el.style && typeof el.style !== "string") throw new Fail("skeleton style")
          const kind = ["", "", "number", "date", "time"][el.type]
          return `{${el.value}, ${kind}${el.style ? `, ${el.style}` : ""}}`
        }
        case T.pound: return "#"
        case T.tag: return `<${el.value}>${serialize(el.children, inPlural)}</${el.value}>`
        case T.select: case T.plural: {
          const plural = el.type === T.plural
          const kind = plural ? (el.pluralType === "ordinal" ? "selectordinal" : "plural") : "select"
          const opts = Object.entries(el.options).map(([k, o]) => `${k} {${serialize(o.value, plural)}}`)
          return `{${el.value}, ${kind}, ${plural && el.offset ? `offset:${el.offset} ` : ""}${opts.join(" ")}}`
        }
      }
      throw new Fail(`unknown node ${el.type}`)
    })
    .join("")
}
const canon = (x) => JSON.stringify(x, (k, v) => (k === "location" ? undefined : v && typeof v === "object" && !Array.isArray(v) ? Object.fromEntries(Object.entries(v).sort(([a], [b]) => (a < b ? -1 : 1))) : v))

// ---------- validation ----------
function signature(ast, acc = new Set()) {
  for (const el of ast) {
    if (el.type === T.literal) continue
    if (el.type === T.pound) acc.add("#")
    else if (el.type === T.tag) {
      acc.add(`tag:${el.value}`)
      signature(el.children, acc)
    } else if (isChoice(el)) {
      acc.add(`${el.type === T.plural ? "plural" : "select"}:${el.value}:${Object.keys(el.options).sort().join("|")}`)
      for (const o of Object.values(el.options)) signature(o.value, acc)
    } else acc.add(`arg:${el.value}:${el.type}:${el.style ?? ""}`)
  }
  return acc
}

function sampleValues(ast, vals = {}) {
  for (const el of ast) {
    if (el.type === T.tag) {
      vals[el.value] = (chunks) => `<${el.value}>${[].concat(chunks).join("")}</${el.value}>`
      sampleValues(el.children, vals)
    } else if (el.type === T.plural || el.type === T.number) vals[el.value] = 3
    else if (el.type === T.select) {
      vals[el.value] = Object.keys(el.options)[0]
      for (const o of Object.values(el.options)) sampleValues(o.value, vals)
    } else if (el.type === T.date || el.type === T.time) vals[el.value] = new Date(0)
    else if (el.type === T.argument && !(el.value in vals)) vals[el.value] = "X"
    if (isChoice(el)) for (const o of Object.values(el.options)) sampleValues(o.value, vals)
  }
  return vals
}

function validateMessage(en, out, lang, built) {
  const enAst = parse(en)
  const outAst = parse(out) // throws on malformed ICU
  if (canon(outAst) !== canon(built)) throw new Fail("re-parse differs from built AST")
  const a = [...signature(enAst)].sort().join(" "), b = [...signature(outAst)].sort().join(" ")
  if (a !== b) throw new Fail(`signature ${a} != ${b}`)
  // Format with every value of every select and a few plural counts; must not throw.
  const base = sampleValues(enAst)
  for (const loc of [lang, "en"]) {
    const fmt = new IntlMessageFormat(out, loc)
    for (const n of [0, 1, 2, 5]) {
      const v = { ...base }
      for (const k of Object.keys(v)) if (typeof v[k] === "number") v[k] = n
      fmt.format(v)
    }
  }
}

function validateUnit(src, out, n) {
  if (typeof out !== "string") return "no text"
  let s = out.trim()
  if (/^["“].*["”]$/s.test(s) && !/^["“]/.test(src)) s = s.slice(1, -1).trim()
  if (!s) return "empty"
  // The model tends to end bare labels with a period the English doesn't have.
  if (!/[.!?…:]$/.test(src) && /[^.]\.$/.test(s)) s = s.slice(0, -1)
  if (/\n/.test(s) && !/\n/.test(src)) return "newline"
  const found = [...s.matchAll(/\{(\d+)\}/g)].map((m) => Number(m[1])).sort((x, y) => x - y)
  if (found.length !== n || found.some((v, i) => v !== i)) return `markers ${found.join(",")} != 0..${n - 1}`
  const rest = s.replace(/\{\d+\}/g, "")
  const srcRest = src.replace(/\{\d+\}/g, "")
  for (const ch of "{}<>#") if (rest.includes(ch) && !srcRest.includes(ch)) return `stray ${ch}`
  if (/[\[\]]/.test(rest) && !/[\[\]]/.test(srcRest)) return "stray brackets"
  if (s.length > 3 * src.length + 30) return "too long"
  if (s.toLowerCase() === src.toLowerCase() && /\p{L}{3,}.*\s.*\p{L}{3,}/u.test(srcRest)) return "unchanged"
  return { text: s }
}

// ---------- cache + API ----------
const cache = new Map() // `${lang}\u0000${src}` -> [raw outputs]
if (fs.existsSync(CACHE))
  for (const line of fs.readFileSync(CACHE, "utf8").split("\n").filter(Boolean)) {
    const { lang, src, out } = JSON.parse(line)
    const k = `${lang}\u0000${src}`
    if (!cache.has(k)) cache.set(k, [])
    cache.get(k).push(out)
  }
const ck = (lang, src) => `${lang}\u0000${src}`
const MAX_ATTEMPTS = 3

let bucket = [] // timestamps of recent requests
const RPM = Number(process.env.RPM || 45)
async function slot() {
  for (;;) {
    const now = Date.now()
    bucket = bucket.filter((t) => now - t < 60_000)
    if (bucket.length < RPM) return bucket.push(now)
    await new Promise((r) => setTimeout(r, 60_000 - (now - bucket[0]) + 50))
  }
}
let apiCalls = 0, apiErrors = 0, quotaExhausted = false
async function callSunbird(lang, text) {
  if (quotaExhausted) return null
  if (FAKE) return "~" + text.split(" ").reverse().join(" ") + "'s"
  for (let attempt = 0; attempt < 6; attempt++) {
    await slot()
    try {
      const res = await fetch("https://api.sunbird.ai/tasks/translate", {
        method: "POST",
        headers: { Authorization: `Bearer ${process.env.SUNBIRD_API_KEY}`, "Content-Type": "application/json" },
        body: JSON.stringify({ source_language: "eng", target_language: LANGS[lang], text }),
        signal: AbortSignal.timeout(120_000),
      })
      apiCalls++
      if (res.status === 429 || res.status >= 500) {
        apiErrors++
        const errBody = await res.text()
        console.log(`HTTP ${res.status} (${lang}) ${errBody.slice(0, 200)}; retry ${attempt}`)
        // The per-minute limit is worth waiting out; the daily quota is not.
        if (/daily quota/i.test(errBody)) {
          quotaExhausted = true
          return null
        }
        await new Promise((r) => setTimeout(r, 5000 * 2 ** attempt))
        continue
      }
      const body = await res.json()
      const o = body.output || {}
      if (!res.ok || o.Error) {
        console.log(`HTTP ${res.status} (${lang}) error: ${JSON.stringify(body).slice(0, 200)}`)
        return null
      }
      return typeof o.translated_text === "string" ? o.translated_text : null
    } catch (e) {
      apiErrors++
      console.log(`fetch error (${lang}): ${e.message}; retry ${attempt}`)
      await new Promise((r) => setTimeout(r, 5000 * 2 ** attempt))
    }
  }
  return null
}

function bestCached(lang, src, n) {
  const outs = cache.get(ck(lang, src)) || []
  let reason = "not translated"
  for (const o of outs) {
    const v = validateUnit(src, o, n)
    if (typeof v === "object") return v
    reason = v
  }
  return { reason, attempts: outs.length }
}

// ---------- messages ----------
const en = JSON.parse(fs.readFileSync(path.join(WEB, "messages/en.json"), "utf8"))
const leaves = []
;(function walk(o, p) {
  for (const [k, v] of Object.entries(o)) typeof v === "object" ? walk(v, [...p, k]) : leaves.push([[...p, k], v])
})(en, [])

function prepare(msg) {
  return hoist(strip(parse(msg)))
}

// Collect unit texts a message needs (throws Fail if not automatable).
function unitsOf(msg) {
  const units = []
  build(prepare(msg), (text, n) => (units.push([text, n]), text))
  return units
}

function translateMessage(msg, lang) {
  const ast = build(prepare(msg), (text, n) => {
    const r = bestCached(lang, text, n)
    if (!r.text) throw new Fail(`unit "${text.slice(0, 60)}": ${r.reason}`)
    return r.text
  })
  const out = serialize(ast)
  if (out === msg) throw new Fail("identical to English")
  validateMessage(msg, out, lang, ast)
  return out
}

// ---------- main ----------
const args = Object.fromEntries(process.argv.slice(2).map((a) => a.replace(/^--/, "").split("=")))
const sections = args.sections ? args.sections.split(",") : []
const langs = args.langs ? args.langs.split(",") : Object.keys(LANGS)
const concurrency = Number(args.concurrency || 4)

const todo = []
const seen = new Set()
for (const [p, msg] of leaves) {
  if (!sections.includes(p[0]) || SKIP.some((r) => r.test(p.join(".")))) continue
  let units
  try {
    units = unitsOf(msg)
  } catch (e) {
    if (!(e instanceof Fail)) throw e
    continue
  }
  for (const lang of langs)
    for (const [text, n] of units) {
      const k = ck(lang, text)
      if (seen.has(k)) continue
      seen.add(k)
      const outs = cache.get(k) || []
      const ok = outs.some((o) => typeof validateUnit(text, o, n) === "object")
      if (!ok && outs.length < MAX_ATTEMPTS) todo.push([lang, text, n, sections.indexOf(p[0])])
    }
}
// Sections in the order given (priority), so each completes in all languages before the next.
todo.sort((a, b) => a[3] - b[3])
console.log(`units to translate: ${todo.length}`)
let done = 0
const cacheFd = fs.openSync(CACHE, "a")
async function worker() {
  while (todo.length && !quotaExhausted) {
    const [lang, text, n] = todo.shift()
    for (let a = (cache.get(ck(lang, text)) || []).length; a < MAX_ATTEMPTS; a++) {
      const out = await callSunbird(lang, text)
      if (out === null) break
      fs.writeSync(cacheFd, JSON.stringify({ lang, src: text, out }) + "\n")
      if (!cache.has(ck(lang, text))) cache.set(ck(lang, text), [])
      cache.get(ck(lang, text)).push(out)
      if (typeof validateUnit(text, out, n) === "object") break
    }
    if (++done % 25 === 0) console.log(`${done} done, ${todo.length} left, calls ${apiCalls}, errors ${apiErrors}`)
  }
}
await Promise.all(Array.from({ length: concurrency }, worker))

// Rebuild every locale file from the cache (all sections, not just this run's).
const report = {}
for (const lang of Object.keys(LANGS)) {
  const out = {}
  const stats = (report[lang] = { bySection: {}, omitted: {} })
  for (const [p, msg] of leaves) {
    const key = p.join(".")
    const s = (stats.bySection[p[0]] ??= { total: 0, translated: 0 })
    s.total++
    if (SKIP.some((r) => r.test(key))) {
      stats.omitted[key] = "kept in English on purpose"
      continue
    }
    try {
      const t = translateMessage(msg, lang)
      let o = out
      for (const seg of p.slice(0, -1)) o = o[seg] ??= {}
      o[p[p.length - 1]] = t
      s.translated++
    } catch (e) {
      stats.omitted[key] = e instanceof Fail ? e.message : `ERROR ${e.message}`
    }
  }
  fs.mkdirSync(OUTDIR, { recursive: true })
  fs.writeFileSync(path.join(OUTDIR, `${lang}.json`), JSON.stringify(out, null, 2) + "\n")
}
fs.writeFileSync(REPORT, JSON.stringify(report, null, 2))
for (const [lang, r] of Object.entries(report)) {
  const t = Object.values(r.bySection).reduce((a, s) => a + s.translated, 0)
  console.log(lang, `${t}/${leaves.length}`)
}
console.log(`api calls ${apiCalls}, errors ${apiErrors}${quotaExhausted ? ", STOPPED: daily quota exhausted" : ""}`)
