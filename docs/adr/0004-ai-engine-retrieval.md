# ADR 0004: AI engine retrieval — multilingual embeddings and local-evidence RAG

**Status:** Accepted and implemented.

## Context

With P4's verdict engine (ADR 0001 "AnalysisProvider", `app/providers/analysis.py`) running
against real traffic, the question came up: what's our actual retrieval-augmented-generation
architecture, how is data chunked, which embedding model fits, and what would genuinely
improve it? This ADR records the audit and the two changes that came out of it.

**What the engine already does (unchanged by this ADR).** `GroqAnalysisProvider` is not
classic RAG over an indexed document collection — it's single-shot search-augmented
generation, closer to Perplexity than to a RAG paper: one live Tavily web search per claim
(`app/providers/source_verification.py`), one Groq chat completion that turns that evidence
into a verdict (`app/providers/explanation.py`). The pgvector index on
`fact_check_reports.embedding` existed only as a dedupe cache — catching a resubmitted
near-identical claim before it cost another search and another Groq call — not as an evidence
corpus anything was retrieved from.

**No chunking exists, and that's deliberate, not a gap.** A text-splitting step only earns
its complexity when there's a long document to split. There isn't one here: submitted claims
are short, Tavily pre-chunks its own results (a title plus a ~500-character snippet, already
sized for the prompt), and every `fact_check_reports` row is a single self-contained unit (one
claim, one summary) rather than a long article body. Introducing a chunker to split nothing
would be exactly the premature complexity this codebase's own conventions warn against. This
becomes worth revisiting only if a future corpus indexes full article bodies rather than
fact-check summaries — noted here so it isn't re-litigated from scratch later.

**The embedding model was English-only.** `all-MiniLM-L6-v2` (sentence-transformers, 384-dim,
CPU, free) has no meaningful multilingual training. Uganda's submissions aren't all English —
FR-SUBMIT-03 names Luganda, Acholi, Runyankole and Ateso (ADR 0003) — so a non-English
resubmission of an already-debunked claim couldn't be matched to its existing report at all;
the dedupe cache silently didn't work across languages.

**The trusted-source registry is thin.** Only 12 of a 50-source target are seeded
(`app/db/sample_data/admin.py`), so `TavilySourceVerifier`'s restricted-search-with-fallback
(`_RESTRICTED_SEARCH_MIN_RESULTS`) almost always falls back to an unrestricted web search.
Independent of this ADR's changes, but it's the reason leaning harder on our own verified
corpus (below) is worth more here than it would be with a mature source registry.

## Decision

### 1. Multilingual embedding model

`EMBEDDING_MODEL` changes from `sentence-transformers/all-MiniLM-L6-v2` to
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
(`app/core/config.py`, `app/providers/embedding.py`). Same sentence-transformers family, same
384-dim output — no new migration needed past `migrations/versions/0004_embedding_dimensions.py`
— but trained across 50+ languages instead of English-only. This is a straight drop-in
replacement with no code change beyond the configured model name.

### 2. Local-evidence retrieval (the RAG upgrade)

The pgvector lookup `GroqAnalysisProvider.analyze` already did for dedupe is widened from a
single nearest-neighbor (`find_nearest`) to a top-K lookup (`VectorDbProvider.find_similar`,
implemented on both `PgVectorProvider` and `PineconeVectorProvider`), then split by distance
into two tiers against two thresholds:

- **`DEDUPE_MAX_COSINE_DISTANCE`** (0.08, unchanged): close enough to be the same claim —
  reused outright, exactly as before.
- **`LOCAL_EVIDENCE_MAX_COSINE_DISTANCE`** (0.3, new): not the same claim, but close enough to
  be useful grounding. These matches are resolved to their `fact_check_reports` rows and
  prepended to the evidence passed into the Explanation Generator
  (`GroqAnalysisProvider._augment_with_local_evidence`), cited back to their own original
  source (`report.citations[0]`, e.g. the AFP article) rather than to Zuula's own report page.

`EvidenceBundle` (`app/providers/source_verification.py`) grew one field,
`local_evidence_count`, saying how many of its leading `sources` are local-evidence matches
rather than `TavilySourceVerifier`'s own live results. `GroqExplanationGenerator`
(`app/providers/explanation.py`) uses it to label each evidence item in the prompt — "(Zuula's
own verified fact-check corpus)" versus "(live web search)" — and to mark local-evidence
citations as always `trusted`, regardless of the thin trusted-source registry's domain list:
a match from our own verified corpus is stronger evidence than an arbitrary web result, and
the model and the reader should be able to tell the two apart.

**This costs nothing extra.** The widened vector-DB lookup is the same one call
`analyze` already made for dedupe, just asking for more rows back — a local Postgres query,
not a second Tavily search or Groq call. The P4 cost constraint (one Tavily search, one Groq
completion, per claim) is unchanged either way.

**Why this design over the alternatives considered:**

- **Corpus-only RAG (drop live Tavily search).** Rejected: can't handle a claim about
  something that happened yesterday. Our verified corpus only grows from claims we've already
  checked; breaking news needs live search regardless of how good local retrieval gets.
- **Agentic/multi-hop RAG** (iterative query reformulation, multiple search rounds per claim).
  Rejected: breaks the one-search/one-call free-tier cost constraint this engine is built
  around (`explanation.py`'s own docstring on why it's one Groq call, not two). Nothing here
  rules it out later if a real evaluation shows the single-call design hurts quality enough to
  justify the extra Groq/Tavily usage.
- **Fine-tuning a model on Uganda fact-check data.** Rejected: no GPU budget, no labelled
  corpus at the scale fine-tuning needs (the entire real corpus is ~360 records, and
  `tools/data-collection/README.md` documents that it's almost entirely debunks), and Groq's
  free-tier hosted models aren't fine-tunable by us anyway.
- **GraphRAG / knowledge-graph retrieval.** Rejected: no graph-shaped data exists here
  (entities/relations between claims, people, events), and building one is a bigger
  investment than this stage's traffic or team size justifies.

## Consequences

- `LOCAL_EVIDENCE_MAX_COSINE_DISTANCE` (0.3) and `LOCAL_EVIDENCE_LIMIT` (3) are picked by
  inspection, the same caveat `DEDUPE_MAX_COSINE_DISTANCE` already carries — revisit once
  real traffic or a labelled eval (`scripts/run_eval.py`) exists to tune against.
  `all-MiniLM-L6-v2`'s 0.08 dedupe threshold was picked by inspection against that model;
  swapping to `paraphrase-multilingual-MiniLM-L12-v2` keeps the same dimensionality but not
  necessarily the same distance distribution, so this threshold should be the first thing
  re-checked once real submissions and `scripts/run_eval.py` give something to tune against.
- Local-evidence retrieval only helps as the verified corpus grows. At ~360 records today
  (almost all AFP Uganda/Kenya/Tanzania debunks — see `tools/data-collection/README.md`), it
  will mostly surface prior debunks on recurring viral claims (the Museveni-health-rumor,
  election-rigging-photo kind of repeat); it won't yet have much to say about genuinely novel
  claims, which is exactly where live Tavily search still carries the load.
- `VectorDbProvider.find_nearest` is now implemented in terms of `find_similar(limit=1)` on
  both providers — a refactor, not a behavior change; existing dedupe tests are unaffected.
