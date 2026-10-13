# data-collection

Collects more Uganda-relevant, human-verified fact-checks from AFP Fact Check Africa via
Google's Fact Check Tools API, in the exact schema `data/fact-checks/seed/*.json` and
`data/fact-checks/eval/*.json` already use. This is how the existing 85 Uganda + 278
Kenya/Tanzania records were collected (see `apps/api/app/db/real_data.py`'s docstring and
commit `fe43d90`), just as a reusable script this time instead of an ad hoc one-off.

**Why AFP only:** Google's Fact Check Tools API indexes ClaimReview markup from many
publishers, but PesaCheck (the other major East Africa fact-checker) isn't indexed there and
its own site blocks automated access with a persistent Cloudflare challenge. AFP Fact Check
Africa is the only usable source through this API for this region.

**Known gap this run should try to close:** every existing real record (all 363) is a
debunk — `false`, `likely-false` or `ai-generated`. None are `authentic` or `unverifiable`.
That's a real skew: a demo/eval corpus that's 100% false makes the verdict engine's behavior
on confirmed-true claims completely untested. `collect.py --include-true` runs a second pass
of queries aimed at AFP's own confirmed-true pieces, but AFP mostly publishes debunks by the
nature of fact-checking, so don't expect this to fully balance the set — report back
whatever ratio actually comes back rather than forcing a target.

## Setup

```bash
# Get a free key: console.cloud.google.com -> enable "Fact Check Tools API" -> Credentials.
# No billing account needed for this API.
export GOOGLE_FACTCHECK_API_KEY=...
```

## Usage

```bash
# Collect new Uganda records, merge into data/fact-checks/seed/afp-fact-check-uganda.json,
# deduping against everything already in seed/ and eval/ (source_url match).
python3 collect.py

# Also search for AFP's confirmed-true pieces (see "known gap" above).
python3 collect.py --include-true

# See what would be collected without writing anything.
python3 collect.py --dry-run

# Cap how many new records to keep (after dedup), e.g. for a quick top-up.
python3 collect.py --limit 200
```

Unmapped `textualRating` strings and off-topic (non-Uganda) results are logged to stderr and
skipped, never guessed — extend `RATING_MAP` in `collect.py` once you see what AFP actually
used for ones logged as unmapped, then rerun.

`cache/` holds the raw API responses this run pulled, so a second run doesn't re-spend the
API's quota re-fetching pages it already has; delete it to force a fresh pull.
