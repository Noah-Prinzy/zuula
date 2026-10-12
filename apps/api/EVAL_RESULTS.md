# P4 verdict-engine eval results (FR-DETECT-03)

**Headline: FR-DETECT-03's >=90% target is NOT MET, and this run could not reliably test it
either way — read "What actually happened" before the numbers below.**

## What actually happened

This is the first time `scripts/run_eval.py` has run against live Groq + Tavily traffic with
real credentials. Both free-tier API keys this project shares across all of today's concurrent
P4/P1 work (~10 Claude sessions building different parts of Zuula today) turned out to be
exhausted or nearly exhausted by the time this harness got its turn, confirmed by direct probes
against both APIs with the exact payload shapes `GroqAnalysisProvider` sends:

- **Groq: daily token quota (200,000 tokens/day on the free tier), not the per-minute one.**
  A direct probe returned `"Rate limit reached ... on tokens per day (TPD): Limit 200000, Used
  199313, Requested 1538. Please try again in 6m7.632s."` This is a rolling quota, not a fixed
  per-minute bucket the harness's original retry/backoff was built to absorb — no amount of
  pacing or short backoff clears a quota that's already almost entirely spent for the day.
  **Result: only 31/278 items (11%) ever got a real Groq verdict back; the other 247 failed
  with HTTP 429 every time, including after retries.**
- **Tavily: monthly search-plan quota, fully exhausted.** A direct probe returned HTTP 432:
  `"This request exceeds your plan's set usage limit."` **148/278 items (53%) got no real web
  evidence at all** — `GroqAnalysisProvider.analyze()` catches this internally and proceeds
  "with no evidence" rather than failing, exactly as it's designed to, but that's a materially
  different (and harder) task than the one the verdict engine is meant to do.

Neither of these is a bug in the harness or in `GroqAnalysisProvider` — they're this project's
shared free-tier capacity being spent elsewhere before this eval's turn. The harness itself was
fixed along the way (see commit history on this branch) to: write results incrementally so a
killed run doesn't lose scored items, support `--resume` to pick up where it left off, parse
Groq's own suggested retry delay instead of guessing, and give up fast on a item once that
delay is clearly a daily-quota wait rather than a short per-minute one — all of which just
changed how fast/safely the harness surfaces this reality, not what it measures.

### The one number worth trusting more than the headline accuracy

Of the 31 items that got a real Groq verdict, **17 also had real Tavily evidence and 14 did
not** (Tavily's quota wall again). Split by that:

- **With real evidence: 11/17 = 64.7%** accuracy.
- **Without evidence (Tavily exhausted): 0/14 = 0.0%** accuracy — every evidence-free guess
  was wrong.

That's a real, if small-sample, signal: this verdict engine's accuracy leans heavily on
evidence actually being retrieved, and a flat "35.5% overall" figure (below) understates how it
performs under normal conditions by mixing in 14 items it never had a fair shot at. 64.7% on
N=17 is still well short of 90%, and nowhere near large enough a sample to responsibly certify
either way — but it's the more honest number to start from.

### Two more things worth knowing when reading the numbers below

- **Dedupe hits are 0/278, and that's structural, not a sign dedupe is broken.** This
  environment runs `EMBEDDING_PROVIDER=stub` (the default), and separately, seeded
  `fact_check_reports` rows (fictional and real-AFP alike) are never given a real embedding at
  seed time — only `app/worker/pipeline.py`'s live submission path writes one. Production
  dedupe isn't exercised by this harness at all right now; `app/db/backfill_embeddings.py`
  (merged separately) exists to close that gap but needs `EMBEDDING_PROVIDER=sentence-transformers`
  to produce a real vector, which this run didn't set.
- **AFP's `claim` field sometimes isn't the false assertion itself.** Spot-checking mismatches
  earlier while building this harness, several AFP records' `claim` text is AFP's own true,
  descriptive headline about a disinformation pattern (e.g. "False quotes and media company
  logos combine to mislead voters in Kenya") rather than the literal false claim circulating —
  real evidence can correctly confirm that *headline* as true, nudging a well-evidenced model
  toward "authentic" on an item whose ground truth is "false". This is a genuine property of
  the eval data, not something to fix in it or in the provider.

### Next steps

- Re-run with `--resume` (already implemented, untested against the full remainder) once more
  of Groq's daily budget and Tavily's monthly quota have recovered — ideally with no other
  session spending the same two keys concurrently, since that's what emptied them before this
  run's turn.
- If a reliable eval needs to run on a predictable schedule, this project's Groq/Tavily keys
  likely need to move off the free tier, or get a dedicated key separate from day-to-day dev
  traffic.

## Raw numbers from this run (278 items, mostly quota-starved — see above)

- Items: 278 (Kenya + Tanzania held-out split)
- Scored (no error): 31/278
- Errors: 247/278
- **Overall accuracy: 11/31 = 35.5%**
- FR-DETECT-03 target (>=90% text accuracy): NOT MET
- Dedupe hits: 0/278
- Tavily failures (evidence-free fallback): 148/278

## Confusion matrix (rows = actual, columns = predicted)

| actual \ predicted | authentic | likely-false | false | ai-generated | unverifiable | (error) |
|---|---|---|---|---|---|---|
| likely-false | 0 | 0 | 0 | 0 | 5 | 31 |
| false | 3 | 0 | 11 | 0 | 12 | 210 |
| ai-generated | 0 | 0 | 0 | 0 | 0 | 6 |

## Accuracy by country

- KE: 9/26 = 34.6%
- TZ: 2/5 = 40.0%

## Accuracy by category

- Economy: no scored items
- Education: 1/1 = 100.0%
- Elections: 0/7 = 0.0%
- Health: 2/4 = 50.0%
- Politics: 5/12 = 41.7%
- Society: 3/7 = 42.9%
- Weather: no scored items

## Note: likely-false / false ground-truth mapping

`app/db/real_data.py`'s AFP-rating -> Verdict mapping is an editorial judgment call, not something AFP itself assigns, so a predicted/actual mismatch across just these two verdicts is a softer miss than e.g. predicting `authentic` for a `false` claim.
- Ground truth `likely-false`, predicted `false`: 0
- Ground truth `false`, predicted `likely-false`: 0
- Accuracy if these two verdicts are treated as equivalent: 35.5%

## Errors

- GroqError: 247
