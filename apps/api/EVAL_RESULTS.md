# P4 verdict-engine eval results (FR-DETECT-03)

**Headline: FR-DETECT-03's >=90% target is NOT MET. The run is now complete (278/278
items attempted), but the result is dominated by Tavily's web-search quota being fully
exhausted for the entire eval — read "What actually happened" before the numbers below.**

## What actually happened

This is the completed run of `scripts/run_eval.py` against live Groq + Tavily traffic,
combining the original attempt (31/278 scored before Groq's daily quota ran out) with a
`--resume` pass that retried the other 247 items once that quota had partially recovered.

- **Groq's daily token quota (200,000 tokens/day, free tier) was repeatedly re-exhausted
  during the resume by other concurrent sessions sharing the same key.** The resume pass
  saw the same `"Rate limit reached ... on tokens per day (TPD)"` error recur several
  times (e.g. `Used 199685/200000`, `Used 199847/200000`) as the quota trickled back and
  got spent again before this harness's turn. The harness's "give up fast on daily-quota
  waits" logic correctly treated each of these as an error and moved on rather than
  blocking, which is why the run reached 278/278 attempted despite the quota fighting it
  the whole way. **Result: 102/278 items (37%) got a real Groq verdict; 176/278 failed
  outright (175 GroqError, 1 transient ConnectionRefusedError from a Postgres restart
  mid-run).**
- **Tavily's monthly search-plan quota was already fully exhausted before the resume
  started, and stayed exhausted for its entire duration.** Every single search attempted
  during the `--resume` pass got Tavily's HTTP 432 ("exceeds your plan's set usage
  limit"). `GroqAnalysisProvider.analyze()` catches this and proceeds "with no evidence"
  rather than failing, exactly as designed — but it means **zero new evidence-backed
  verdicts were produced during the entire resume.** All 17 evidence-backed scored items
  in this report are the same 17 from the original attempt, before Tavily's quota died.
  **260/278 items (94%) got no real web evidence at all**, up from 148/278 before the
  resume.

Neither of these is a bug in the harness or in `GroqAnalysisProvider` — both are this
project's shared free-tier capacity being spent elsewhere before/during this eval's turn.

### The one number worth trusting more than the headline accuracy

Of the 102 items that got a real Groq verdict, **17 had real Tavily evidence (frozen at
17 — no new evidence came in during the resume) and 85 did not.** Split by that:

- **With real evidence: 11/17 = 64.7%** accuracy — unchanged from the first attempt,
  since no new evidence-backed items were added.
- **Without evidence (Tavily exhausted): 0/85 = 0.0%** accuracy — every evidence-free
  guess was wrong, across all 85 of them. This is a much larger, starker sample than the
  14 we had before, and it says the same thing more forcefully: **on this held-out set,
  this verdict engine has not gotten a single evidence-free call right.**

That split is the honest way to read this run. The flat **"10.8% overall" figure below is
not a regression** — it's the same 11 correct answers as before, diluted by 71 more
evidence-free items (all wrong) that the resume was able to attempt once Groq's quota
briefly reopened. The underlying analyzer didn't get worse; the eval just got to test more
of its worst-case behavior (no evidence) and none of its best-case behavior (evidence),
because Tavily had nothing left to give for the entire second half of this run.

### Two more things worth knowing when reading the numbers below

- **Dedupe hits are 0/278, and that's structural, not a sign dedupe is broken.** This
  environment runs `EMBEDDING_PROVIDER=stub` (the default), and separately, seeded
  `fact_check_reports` rows (fictional and real-AFP alike) are never given a real embedding
  at seed time — only `app/worker/pipeline.py`'s live submission path writes one.
  Production dedupe isn't exercised by this harness at all right now;
  `app/db/backfill_embeddings.py` (merged separately) exists to close that gap but needs
  `EMBEDDING_PROVIDER=sentence-transformers` to produce a real vector, which this run
  didn't set.
- **AFP's `claim` field sometimes isn't the false assertion itself.** Spot-checking
  mismatches earlier while building this harness, several AFP records' `claim` text is
  AFP's own true, descriptive headline about a disinformation pattern (e.g. "False quotes
  and media company logos combine to mislead voters in Kenya") rather than the literal
  false claim circulating — real evidence can correctly confirm that *headline* as true,
  nudging a well-evidenced model toward "authentic" on an item whose ground truth is
  "false". This is a genuine property of the eval data, not something to fix in it or in
  the provider.

### Next steps

- **This project's Groq/Tavily keys need to move off the free tier, or get a dedicated key
  separate from day-to-day dev traffic, before this eval can produce a trustworthy
  headline number.** Both quotas were fully or mostly spent by other concurrent work
  before and during this eval's only two attempts — a third attempt would very likely hit
  the same wall.
- The evidence-backed sample (N=17, 64.7%) is the only part of this run worth treating as
  a real signal, and it's still too small and too far under 90% to certify FR-DETECT-03
  either way. A re-run with a fresh/dedicated Tavily quota, large enough to cover all 278
  items with real evidence, is what this eval actually needs to produce a meaningful
  number.

## Raw numbers from this run (278 items, resume completed; Tavily exhausted throughout)

- Items: 278 (Kenya + Tanzania held-out split)
- Scored (no error): 102/278
- Errors: 176/278
- **Overall accuracy: 11/102 = 10.8%** (see "one number worth trusting" above)
- FR-DETECT-03 target (>=90% text accuracy): NOT MET
- Dedupe hits: 0/278
- Tavily failures (evidence-free fallback): 260/278

## Confusion matrix (rows = actual, columns = predicted)

| actual \ predicted | authentic | likely-false | false | ai-generated | unverifiable | (error) |
|---|---|---|---|---|---|---|
| likely-false | 0 | 0 | 0 | 0 | 15 | 21 |
| false | 3 | 0 | 11 | 0 | 71 | 151 |
| ai-generated | 0 | 0 | 0 | 0 | 2 | 4 |

## Accuracy by country

- KE: 9/90 = 10.0%
- TZ: 2/12 = 16.7%

## Accuracy by category

- Economy: 0/6 = 0.0%
- Education: 1/3 = 33.3%
- Elections: 0/13 = 0.0%
- Health: 2/8 = 25.0%
- Politics: 5/37 = 13.5%
- Society: 3/31 = 9.7%
- Weather: 0/4 = 0.0%

## Note: likely-false / false ground-truth mapping

`app/db/real_data.py`'s AFP-rating -> Verdict mapping is an editorial judgment call, not something AFP itself assigns, so a predicted/actual mismatch across just these two verdicts is a softer miss than e.g. predicting `authentic` for a `false` claim.
- Ground truth `likely-false`, predicted `false`: 0
- Ground truth `false`, predicted `likely-false`: 0
- Accuracy if these two verdicts are treated as equivalent: 10.8%

## Errors

- GroqError: 175
- ConnectionRefusedError: 1
