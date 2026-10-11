# P4 verdict-engine eval results (FR-DETECT-03)

**Status: blocked tonight by Groq's free-tier daily token quota, not yet run to completion.**

## What happened

Two real bugs were found and fixed while trying to actually run `scripts/run_eval.py` against
live Groq/Tavily traffic for the first time with real credentials:

1. **`_tavily_search_with_retry()` didn't forward `include_domains`.** This branch was cut
   before #52 (trusted-sources Tavily restriction) merged into `main`. #52 added an
   `include_domains` parameter to `app/providers/tavily.py`'s `tavily_search()`, and
   `app/providers/analysis.py` now calls it with that argument — but the eval harness's
   retry-wrapping drop-in replacement still had the old signature, so every real call raised
   `TypeError: _tavily_search_with_retry() got an unexpected keyword argument 'include_domains'`.
   Fixed: the wrapper now accepts and forwards `include_domains`.

2. **A request-pacing throttle was added, then found to not be the actual problem.** The first
   symptom (every item failing with HTTP 429 even after the harness's own retry/backoff) looked
   like Groq's advertised `x-ratelimit-limit-tokens: 8000` (tokens/minute) being exceeded by a
   single `analyze()` call's prompt (system prompt + claim + up to 5 Tavily snippets, plus
   gpt-oss-120b's hidden reasoning tokens) — a request bigger than the per-minute bucket would
   431 forever regardless of backoff. A `_Pacer` was added to `scripts/run_eval.py` (minimum
   spacing between dispatching Groq calls, `--request-interval`, default 20s) as a defensive fix
   for that scenario. It's harmless to keep but **did not fix tonight's actual problem**.

## The real blocker

A direct probe against the live Groq API (same model, same realistic prompt, no `max_tokens`
cap — matching exactly what `GroqAnalysisProvider._verdict()` sends) returned:

```
HTTP 429: "Rate limit reached for model `openai/gpt-oss-120b` ... on tokens per day (TPD):
Limit 200000, Used 199243, Requested 775."
```

This is a **daily** quota (200,000 tokens/day on the free tier), not the per-minute one the
pacer guards against, and it's almost entirely spent for today — most likely consumed across
today's cumulative work on this key (the verdict-engine build in #46, the trusted-sources work
in #52, and ad-hoc testing, including the probes used to diagnose this). No client-side pacing
or retry/backoff can work around a daily quota; only waiting for it to reset (commonly midnight
UTC for Groq, unconfirmed) or upgrading off the free tier fixes it.

**No eval numbers in this document are real yet.** The 3-item smoke runs attempted while
diagnosing this all failed outright (0 scored, 100% error) — they are not a sample of real
accuracy, just evidence of the quota wall. Fabricating a number here would misrepresent whether
FR-DETECT-03's 90% target is met; that question is still open.

## Next steps

- Retry the real run after the daily quota window resets (likely UTC midnight) — the harness
  itself (`scripts/run_eval.py`) is now fixed and ready; the `include_domains` bug this would
  otherwise hit on every item is fixed.
- If quota continues to be a problem even outside quota-exhaustion windows, consider whether
  this project's Groq key should move off the free tier before relying on daily eval runs, or
  cache/throttle more aggressively across the team's combined usage.
