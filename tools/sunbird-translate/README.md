# sunbird-translate

Machine-drafts `apps/web/messages/{lg,ach,nyn,teo}.json` from `en.json` with Sunbird AI's
translation API. The output is a first pass for native-speaker review, not a finished translation.

Needs `apps/web` dependencies installed (`npm ci` there) and Node 22+.

```bash
# Translate the named sections, in this priority order, for all four languages.
# It stops by itself when Sunbird's daily quota runs out; rerun the next day.
SUNBIRD_API_KEY=... NODE_USE_ENV_PROXY=1 node translate.mjs --sections=Home,Auth,Verify

# Rebuild the locale files from cache.jsonl only (no API calls).
node translate.mjs --sections=

# Count what a run would send, without calling the API.
node translate.mjs --sections=Home,Auth --dry

# Check every locale message against en.json (exit 1 on any failure).
node check-locales.mjs

# Dry run with a fake translator that reverses word order (writes to fake-out/, no API calls).
FAKE=1 RPM=100000 node translate.mjs --sections=Common --concurrency=20
DIR=$PWD/fake-out node check-locales.mjs
```

`NODE_USE_ENV_PROXY=1` is only needed where outbound HTTPS goes through a proxy.

## How ICU syntax is kept out of the API

Tests against the live API showed the model translates named placeholders (`{name}` became
`{erinnya}` in Luganda) and drops paired tags. So the translator never sends ICU syntax:

- Each message is parsed with the ICU parser next-intl uses at runtime (the copy inside `intl-messageformat`).
- Plural and select are moved to the outside, so each option becomes a whole sentence. The words
  `plural`, `select`, the option keys and variable names are never sent.
- Arguments, `#`, ALL-CAPS tokens, numbers, paths, URLs, emails and brand names become `{0}`,
  `{1}`, … markers. Numeric markers survived in all four languages.
- Text inside rich tags is translated on its own. `<code>`, `<email>`, `<q>` and `<time>` are kept verbatim.
- A reply is used only if every marker comes back exactly once and nothing like `{ } < > #`
  appears that wasn't in the input. Otherwise it's retried, up to 3 attempts, then the key is left
  out, so it falls back to English.
- The message is rebuilt and parsed again, and must match what was built exactly.

## When the model returns English

The model often gives short capitalised labels back unchanged ("Link", "Password", "Audit Log").
A reply like that is still used, so names and acronyms (WhatsApp, SMS, API) read correctly, but
the text is sent again:

- First as is, up to 3 attempts in all. Replies vary, so a later one is sometimes a translation.
- Then reworded: in lowercase, and for short labels with "the" in front ("the password"). The
  capital is restored in the result. Names (Uganda, Luganda, Victoria University, …) are never
  reworded, because the model then makes something up.

A reply that only arrives after the English one must also look like a translation: it may not
reuse an English word from the source ("The in-app", "Email ngin", "Filter ({count})") or be more
than twice as long in words. Reworded replies are stored in `cache.jsonl` with a `for` field
naming the original text, so they are reused like any other reply.

`check-locales.mjs` is independent of the translator. It requires each locale message to have
exactly English's placeholders, tags and plural/select options. It also formats each one through
next-intl's `createTranslator`, for every select value and several plural counts.

## Checking the layout in every language

Translations run longer than English (about 1.1–1.3x on average, up to 2x, with single words of
20+ letters), which can push text out of buttons, badges, tabs and rows. `check-overflow.mjs`
loads every page of a running build in each language at 360, 768 and 1280px. It reports:
horizontal page scroll, text wider or taller than its box, text pushed off-screen, and text cut off
by a clipping parent. It sorts each issue into one of two groups: it also happens in English
(pre-existing), or only in a translation. It exits 1 on any translation-only issue.

`pseudo-locale.mjs` fills every message with lengthened English (each word doubled, placeholders
intact), so pages that aren't translated yet can be checked too. Build it in place of one
locale, scan, then put the real file back.

```bash
# Playwright is not an apps/web dependency: install it anywhere and point NODE_PATH at it.
npm i --prefix /tmp/pw playwright
cd ../../apps/web && npm run build && npx next start -p 3000 &
NODE_PATH=/tmp/pw/node_modules node check-overflow.mjs                  # all pages, all languages
NODE_PATH=/tmp/pw/node_modules node check-overflow.mjs --locales=lg --routes=/,/verify

# Worst case for pages not translated yet: build with the pseudo-locale standing in for teo.
cp ../../apps/web/messages/teo.json /tmp/teo.json && node pseudo-locale.mjs > ../../apps/web/messages/teo.json
(cd ../../apps/web && npm run build) && cp /tmp/teo.json ../../apps/web/messages/teo.json
```

## Files

- `cache.jsonl`: every raw reply from Sunbird. Commit it: it's what lets a later run resume
  without paying for the same calls again. Losing it means rebuilding from scratch, which would
  empty the locale files.
- `report.json` (ignored): per-section coverage and the reason each key was left out.
- `overflow-report.json` (ignored): every layout issue from the last `check-overflow.mjs` run.

## Sunbird API notes (checked live, 2026-09-24)

- Endpoint: `POST https://api.sunbird.ai/tasks/translate`, with `Authorization: Bearer <key>` and
  body `{"source_language": "eng", "target_language": "lug", "text": "..."}`. The old
  `/tasks/nllb_translate` returns 405.
- The translation is in `output.translated_text`. `output.text` echoes the input.
- Limits: about 50 requests a minute, and a daily quota of roughly 450–500 requests. Going over the
  daily quota returns 429 `"Daily quota exceeded"`.
