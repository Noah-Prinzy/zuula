// Writes a pseudo-locale: every message from en.json with each word doubled in length, which
// matches the longest real translations (about 2x English, single words over 20 letters).
// ICU arguments, tags and plural/select structure are left intact. Scanning the app with it
// finds layout that breaks under long text before real translations reach those pages.
//
//   node pseudo-locale.mjs > /tmp/pseudo.json
import fs from "node:fs"
import { createRequire } from "node:module"

const WEB = new URL("../../apps/web", import.meta.url).pathname
const require = createRequire(WEB + "/package.json")
const { parse } = require(WEB + "/node_modules/intl-messageformat/node_modules/@formatjs/icu-messageformat-parser")
const { printAST } = require(WEB + "/node_modules/@formatjs/icu-messageformat-parser/printer.js")

// Doubles words of 3+ letters by echoing their vowels: "Save changes" -> "Saaveee chaangeees".
const stretch = (text) =>
  text.replace(/[A-Za-z][a-z]{2,}/g, (w) => w + w.replace(/[^aeiou]/gi, "").padEnd(w.length, "e").toLowerCase())

function walk(ast) {
  for (const el of ast) {
    if (el.type === 0) el.value = stretch(el.value)
    else if (el.type === 8) walk(el.children)
    else if (el.type === 5 || el.type === 6) for (const o of Object.values(el.options)) walk(o.value)
  }
  return ast
}

const convert = (o) =>
  Object.fromEntries(Object.entries(o).map(([k, v]) => [k, typeof v === "object" ? convert(v) : printAST(walk(parse(v)))]))

process.stdout.write(JSON.stringify(convert(JSON.parse(fs.readFileSync(`${WEB}/messages/en.json`, "utf8"))), null, 2) + "\n")
