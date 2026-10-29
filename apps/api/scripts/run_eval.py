"""P4 verdict-engine evaluation harness (FR-DETECT-03): runs `GroqAnalysisProvider.analyze()`
over the held-out `data/fact-checks/eval/*.json` split (278 AFP-verified Kenya/Tanzania
fact-checks) and scores its `.verdict` against each item's ground-truth verdict.

Deliberately reads the eval directory itself rather than going through app/db/real_data.py,
whose docstring says that module must never read it (it's a held-out split for this harness,
not for seeding).

Needs a real PostgreSQL+pgvector database for the dedupe check inside `analyze()` — by default
it provisions its own (`{TEST_DATABASE_URL}_eval`), migrated and seeded the same way
tests/dbutil.py does (see tests/db/test_seed_real.py's REAL_DB_URL for the same convention),
so it never touches whatever TEST_DATABASE_URL the test suite itself is using.

Usage:
    python -m scripts.run_eval                     # full 278-item run
    python -m scripts.run_eval --limit 8            # smoke test on a small subset
    python -m scripts.run_eval --concurrency 1 --limit 5 --out /tmp/smoke.jsonl

Needs GROQ_API_KEY and TAVILY_API_KEY set (real keys — this calls the live APIs and spends
free-tier quota); GEMINI_API_KEY, OPENROUTER_API_KEY and EXA_API_KEY too, to measure the engine
as production runs it (Milestone D3–D5 fallbacks). Prints a summary report to stdout; per-item
results go to --out as JSONL.

**Blind to the answer key (default, Milestone D9).** Every item is an AFP fact-check, and AFP
Fact Check is a trusted source since D8, so the search would usually return AFP's own verdict
on the very claim being scored. Search results from afp.com are dropped before the model sees
them (`--open` keeps them), so the number measures the engine's judgement from other evidence.
The item set has no true claims (236 false, 36 likely-false, 6 AI-generated), so accuracy here
says nothing about false alarms on true claims; the report says so.
"""

import argparse
import asyncio
import json
import logging
import re
import sys
import time
from collections import Counter, defaultdict
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from pathlib import Path

from alembic import command
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

SCRIPTS_DIR = Path(__file__).resolve().parent
API_ROOT = SCRIPTS_DIR.parent
REPO_ROOT = API_ROOT.parents[1]
EVAL_DATA_DIR = REPO_ROOT / "data" / "fact-checks" / "eval"

sys.path.insert(0, str(API_ROOT))

from app.providers import explanation as explanation_module  # noqa: E402
from app.providers import source_verification as search_module  # noqa: E402
from app.providers.analysis import GroqError, get_analysis_provider  # noqa: E402
from app.providers.exa import exa_search as _real_exa_search  # noqa: E402
from app.providers.tavily import TavilySearchError  # noqa: E402
from app.providers.tavily import tavily_search as _real_tavily_search  # noqa: E402
from tests.dbutil import TEST_DATABASE_URL as _DEFAULT_TEST_DATABASE_URL  # noqa: E402
from tests.dbutil import alembic_config, recreate_database, seed_database  # noqa: E402

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("zuula.scripts.run_eval")

EVAL_DB_URL = f"{_DEFAULT_TEST_DATABASE_URL}_eval"

VERDICTS = ("authentic", "likely-false", "false", "ai-generated", "unverifiable")

_event: ContextVar[dict] = ContextVar("eval_event")


class _Pacer:
    """Groq's free tier on gpt-oss-120b caps at 8000 tokens/minute (confirmed via its
    `x-ratelimit-limit-tokens` response header) — far below what the retry backoff in
    `analyze_with_retry` can work around, since a single analyze() call's prompt (system
    prompt + claim + up to 5 Tavily snippets) plus gpt-oss-120b's hidden reasoning tokens can
    approach or exceed that whole per-minute budget on its own: no amount of retrying fixes a
    request that's bigger than the bucket. This enforces a minimum spacing between dispatching
    Groq calls so the harness stays under budget instead of needing the 429 retry path at all."""

    def __init__(self, min_interval: float):
        self._min_interval = min_interval
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next_at - now)
            self._next_at = max(now, self._next_at) + self._min_interval
        if delay:
            await asyncio.sleep(delay)


_pacer: _Pacer | None = None


# ---- retry/backoff instrumentation (wraps the real network calls; changes no provider logic) ----


# Domains whose pages are the answer key: AFP publishes every item in the eval set.
ANSWER_KEY_DOMAINS = ("afp.com",)
_blind = True


def _without_answer_key(results):
    if not _blind:
        return results
    kept = [
        r
        for r in results
        if not any(
            search_module.domain_of(r.url) == d or search_module.domain_of(r.url).endswith("." + d)
            for d in ANSWER_KEY_DOMAINS
        )
    ]
    event = _event.get(None)
    if event is not None:
        event["answer_key_dropped"] = event.get("answer_key_dropped", 0) + len(results) - len(kept)
    return kept


async def _exa_search_recorded(**kwargs):
    """Drop-in for source_verification's `exa_search` (Tavily's backup): records that the
    backup was used and drops the answer key, like the Tavily wrapper below."""
    event = _event.get(None)
    if event is not None:
        event["search"] = "Exa"
    return _without_answer_key(await _real_exa_search(**kwargs))


async def _first_json_recorded(models, messages, *, timeout, what):
    """Drop-in for explanation's `first_json`: records which model gave the verdict."""
    data, model = await _real_first_json(models, messages, timeout=timeout, what=what)
    event = _event.get(None)
    if event is not None:
        event["model"] = f"{model.name}: {model.model}"
    return data, model


_real_first_json = explanation_module.first_json


async def _tavily_search_with_retry(
    *, api_key, api_url, query, max_results=5, timeout=20.0, include_domains=None
):
    """Drop-in replacement for app.providers.source_verification's `tavily_search`: retries a
    transient (429/5xx/network) failure a few times before giving up, so a Tavily hiccup
    doesn't permanently degrade one claim to "no evidence" the way a bare call would. On final
    failure it raises the same TavilySearchError the real function would, so
    GroqAnalysisProvider.analyze()'s own `except TavilySearchError` handles it exactly as
    before."""
    event = _event.get(None)
    attempt = 0
    while True:
        try:
            result = await _real_tavily_search(
                api_key=api_key,
                api_url=api_url,
                query=query,
                max_results=max_results,
                timeout=timeout,
                include_domains=include_domains,
            )
            if event is not None:
                event["tavily_called"] = True
                event.setdefault("search", "Tavily")
            return _without_answer_key(result)
        except TavilySearchError as exc:
            attempt += 1
            transient = any(code in str(exc) for code in ("429", "500", "502", "503", "504")) or (
                "HTTP" not in str(exc)
            )
            if event is not None:
                event["tavily_called"] = True
                event["tavily_error"] = str(exc)
            if transient and attempt <= 3:
                await asyncio.sleep(2**attempt)
                continue
            raise


_RETRY_AFTER_RE = re.compile(r"try again in (?:(\d+)m)?([\d.]+)s")

# Above this, don't bother retrying within one item: app/providers/analysis.py's GroqError now
# carries the response body (see its diff), and a real 429 body there can be either a
# per-minute throttle (clears in seconds) or Groq's *daily* token quota (clears only once
# enough of a rolling 24h window ages out — minutes, observed up to ~6 on this project's key).
# A per-item retry loop blocking for minutes stalls the whole run's throughput for one item;
# better to fail this item fast and let --resume pick it up once the daily budget recovers.
MAX_INLINE_RETRY_WAIT_SECONDS = 90.0


def _retry_after_seconds(message: str) -> float | None:
    match = _RETRY_AFTER_RE.search(message)
    if not match:
        return None
    minutes, seconds = match.groups()
    return (int(minutes) * 60 if minutes else 0) + float(seconds)


async def analyze_with_retry(provider, *, db, content_type, text, language, max_attempts=6):
    """Retries a transient GroqError (429/5xx/network) with backoff, on top of the proactive
    pacing in _Pacer. A non-transient failure (bad request, malformed JSON response) is raised
    immediately — retrying it would just reproduce the same deterministic failure. When Groq's
    error names its own suggested retry delay, that's used instead of guessing via exponential
    backoff — except past MAX_INLINE_RETRY_WAIT_SECONDS, where this gives up on the item instead
    of blocking the whole run on one daily-quota-exhausted call (see its docstring)."""
    attempt = 0
    while True:
        try:
            if _pacer is not None:
                await _pacer.wait()
            return await provider.analyze(
                db=db, content_type=content_type, text=text, language=language
            )
        except GroqError as exc:
            attempt += 1
            retry_after = _retry_after_seconds(str(exc))
            if retry_after is not None and retry_after > MAX_INLINE_RETRY_WAIT_SECONDS:
                raise
            transient = any(code in str(exc) for code in ("429", "500", "502", "503", "504")) or (
                "HTTP" not in str(exc)
            )
            event = _event.get(None)
            if event is not None:
                event["groq_error"] = str(exc)
            if transient and attempt <= max_attempts:
                wait = retry_after + 1 if retry_after is not None else min(2**attempt, 60)
                await asyncio.sleep(wait)
                continue
            raise


def _instrument_dedupe(provider) -> None:
    """Records whether `analyze()` reused an existing report instead of calling out, without
    changing what it returns."""
    original = provider._reuse_report

    async def recording(db, match, embedding):
        result = await original(db, match, embedding)
        event = _event.get(None)
        if event is not None:
            event["dedupe_hit"] = result is not None
        return result

    provider._reuse_report = recording


# ---- eval data ----


@dataclass
class EvalItem:
    idx: int
    country: str
    category: str
    claim: str
    actual_verdict: str
    source_url: str


def load_eval_items(eval_dir: Path) -> list[EvalItem]:
    records: list[dict] = []
    for path in sorted(eval_dir.glob("*.json")):
        records.extend(json.loads(path.read_text(encoding="utf-8")))
    records.sort(key=lambda r: (r["country"], r["source_url"]))
    return [
        EvalItem(
            idx=i,
            country=r["country"],
            category=r.get("category") or "Unknown",
            claim=r["claim"],
            actual_verdict=r["verdict"],
            source_url=r["source_url"],
        )
        for i, r in enumerate(records, start=1)
    ]


@dataclass
class ItemResult:
    idx: int
    country: str
    category: str
    actual_verdict: str
    predicted_verdict: str | None = None
    confidence: int | None = None
    dedupe_hit: bool = False
    tavily_called: bool = False
    tavily_error: str | None = None
    groq_error: str | None = None
    error: str | None = None
    seconds: float = 0.0
    model: str | None = None  # which model in the D3 chain gave the verdict
    search: str | None = None  # Tavily, or Exa when Tavily failed
    answer_key_dropped: int = 0  # afp.com results removed (blind run)
    citations: int = 0


async def process_item(
    provider, engine, item: EvalItem, semaphore: asyncio.Semaphore
) -> ItemResult:
    async with semaphore:
        token = _event.set({"dedupe_hit": False, "tavily_called": False})
        started = time.monotonic()
        result = ItemResult(
            idx=item.idx,
            country=item.country,
            category=item.category,
            actual_verdict=item.actual_verdict,
        )
        try:
            async with AsyncSession(engine, expire_on_commit=False) as db:
                analysis = await analyze_with_retry(
                    provider, db=db, content_type="text", text=item.claim, language="en"
                )
            result.predicted_verdict = analysis.verdict
            result.confidence = analysis.confidence
            result.citations = len(analysis.citations)
        except Exception as exc:  # noqa: BLE001 - one bad item must not abort the run
            result.error = f"{type(exc).__name__}: {exc}"
            logger.warning("Item %s failed: %s", item.idx, result.error)
        finally:
            event = _event.get()
            result.dedupe_hit = event.get("dedupe_hit", False)
            result.tavily_called = event.get("tavily_called", False)
            result.tavily_error = event.get("tavily_error")
            result.groq_error = event.get("groq_error")
            result.model = event.get("model")
            result.search = event.get("search")
            result.answer_key_dropped = event.get("answer_key_dropped", 0)
            result.seconds = time.monotonic() - started
            _event.reset(token)
        return result


# ---- reporting ----


def _accuracy(results: list[ItemResult]) -> tuple[int, int]:
    scored = [r for r in results if r.predicted_verdict is not None]
    correct = sum(1 for r in scored if r.predicted_verdict == r.actual_verdict)
    return correct, len(scored)


def build_report(results: list[ItemResult]) -> str:
    lines: list[str] = []
    total = len(results)
    errors = [r for r in results if r.error is not None]
    correct, scored = _accuracy(results)
    accuracy = correct / scored if scored else 0.0

    lines.append("# Verdict-engine eval results (FR-DETECT-03)\n")
    lines.append(f"- Items: {total} (Kenya + Tanzania held-out split)")
    lines.append(
        "- Mode: "
        + ("blind (afp.com results dropped: the answer key)" if _blind else "open (afp.com kept)")
        + f"; {sum(1 for r in results if r.answer_key_dropped)} items had AFP results removed"
    )
    lines.append(
        "- **Caveat:** every item is false, likely-false or AI-generated; there are no true "
        "claims, so this cannot show false alarms on true claims."
    )
    lines.append(f"- Scored (no error): {scored}/{total}")
    lines.append(f"- Errors: {len(errors)}/{total}")
    lines.append(f"- **Overall accuracy: {correct}/{scored} = {accuracy:.1%}**")
    lines.append(
        f"- FR-DETECT-03 target (>=90% text accuracy): {'MET' if accuracy >= 0.90 else 'NOT MET'}"
    )
    dedupe_hits = sum(1 for r in results if r.dedupe_hit)
    lines.append(f"- Dedupe hits: {dedupe_hits}/{total}")
    tavily_failures = sum(1 for r in results if r.tavily_error)
    lines.append(f"- Tavily failures: {tavily_failures}/{total}")
    falsish = ("false", "likely-false")
    caught = sum(
        1 for r in results if r.predicted_verdict in falsish and r.actual_verdict in falsish
    )
    false_family = sum(
        1 for r in results if r.predicted_verdict is not None and r.actual_verdict in falsish
    )
    if false_family:
        lines.append(
            f"- **Flagged as false or likely false** (of claims that are): "
            f"{caught}/{false_family} = {caught / false_family:.1%}"
        )
    no_evidence = sum(1 for r in results if r.predicted_verdict is not None and not r.citations)
    lines.append(f"- Verdicts citing no source: {no_evidence}/{scored}")
    for label, key in (("Verdict model", "model"), ("Search", "search")):
        counts = Counter(getattr(r, key) or "(none)" for r in results if r.predicted_verdict)
        lines.append(f"- {label}: " + ", ".join(f"{k} {v}" for k, v in counts.most_common()))
    lines.append("")

    lines.append("## Confusion matrix (rows = actual, columns = predicted)\n")
    header = "| actual \\ predicted | " + " | ".join(VERDICTS) + " | (error) |"
    lines.append(header)
    lines.append("|" + "---|" * (len(VERDICTS) + 2))
    for actual in VERDICTS:
        row = [r for r in results if r.actual_verdict == actual]
        if not row:
            continue
        counts = Counter(r.predicted_verdict for r in row if r.predicted_verdict is not None)
        err_count = sum(1 for r in row if r.error is not None)
        cells = [str(counts.get(v, 0)) for v in VERDICTS]
        lines.append(f"| {actual} | " + " | ".join(cells) + f" | {err_count} |")
    lines.append("")

    lines.append("## Accuracy by country\n")
    by_country: dict[str, list[ItemResult]] = defaultdict(list)
    for r in results:
        by_country[r.country].append(r)
    for country, rows in sorted(by_country.items()):
        c, s = _accuracy(rows)
        line = f"- {country}: {c}/{s} = {c / s:.1%}" if s else f"- {country}: no scored items"
        lines.append(line)
    lines.append("")

    lines.append("## Accuracy by category\n")
    by_cat: dict[str, list[ItemResult]] = defaultdict(list)
    for r in results:
        by_cat[r.category].append(r)
    for cat, rows in sorted(by_cat.items()):
        c, s = _accuracy(rows)
        lines.append(f"- {cat}: {c}/{s} = {c / s:.1%}" if s else f"- {cat}: no scored items")
    lines.append("")

    likely_false_as_false = sum(
        1 for r in results if r.actual_verdict == "likely-false" and r.predicted_verdict == "false"
    )
    false_as_likely_false = sum(
        1 for r in results if r.actual_verdict == "false" and r.predicted_verdict == "likely-false"
    )
    lines.append("## Note: likely-false / false ground-truth mapping\n")
    lines.append(
        "`app/db/real_data.py`'s AFP-rating -> Verdict mapping is an editorial judgment call, "
        "not something AFP itself assigns, so a predicted/actual mismatch across just these two "
        "verdicts is a softer miss than e.g. predicting `authentic` for a `false` claim.\n"
        f"- Ground truth `likely-false`, predicted `false`: {likely_false_as_false}\n"
        f"- Ground truth `false`, predicted `likely-false`: {false_as_likely_false}\n"
        f"- Accuracy if these two verdicts are treated as equivalent: "
        f"{(correct + likely_false_as_false + false_as_likely_false) / scored:.1%}"
        if scored
        else ""
    )

    if errors:
        lines.append("\n## Errors\n")
        error_kinds = Counter(e.error.split(":")[0] for e in errors)
        for kind, n in error_kinds.most_common():
            lines.append(f"- {kind}: {n}")

    return "\n".join(lines)


# ---- setup + main ----


def setup_database(database_url: str) -> None:
    # Mirrors tests/conftest.py's migrated_db_url fixture: recreate/seed each run their own
    # asyncio.run(), and alembic's env.py does the same internally for the upgrade — none of
    # this may run inside an already-running event loop (asyncio.run() refuses to nest).
    asyncio.run(recreate_database(database_url))
    command.upgrade(alembic_config(database_url), "head")
    asyncio.run(seed_database(database_url, include_real=True))


def _load_done(out_path: Path) -> dict[int, ItemResult]:
    """Loads already-written per-item results from a prior (possibly killed) run, keyed by
    idx, so a resumed run skips re-spending API quota on items it already scored."""
    if not out_path.exists():
        return {}
    done: dict[int, ItemResult] = {}
    for line in out_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        done[row["idx"]] = ItemResult(**row)
    return done


async def run(args: argparse.Namespace) -> list[ItemResult]:
    global _pacer
    items = load_eval_items(EVAL_DATA_DIR)
    if args.limit:
        items = items[: args.limit]

    done = _load_done(args.out) if args.resume else {}
    remaining = [item for item in items if item.idx not in done]
    if done:
        print(f"Resuming: {len(done)}/{len(items)} items already scored in {args.out}")

    global _blind
    _blind = not args.open
    _pacer = _Pacer(args.request_interval)
    search_module.tavily_search = _tavily_search_with_retry
    search_module.exa_search = _exa_search_recorded
    explanation_module.first_json = _first_json_recorded
    provider = get_analysis_provider()
    if type(provider).__name__ != "GroqAnalysisProvider":
        raise SystemExit(
            "get_analysis_provider() returned a stub — set GROQ_API_KEY and TAVILY_API_KEY "
            "before running the eval."
        )
    _instrument_dedupe(provider)

    engine = create_async_engine(args.database_url, poolclass=NullPool)
    semaphore = asyncio.Semaphore(args.concurrency)
    results: list[ItemResult] = list(done.values())
    # Append-and-flush after every item (not just at the end) so a killed/crashed run only
    # loses the one in-flight item's quota, not the whole batch — the earlier version wrote
    # --out solely in main() after run() returned, so a background-timeout kill mid-run (as
    # happened on the first full-278 attempt, killed at 50/278) discarded every scored item.
    out_mode = "a" if (args.resume and done) else "w"
    try:
        print(f"Running {len(remaining)} remaining items at concurrency {args.concurrency} ...")
        with args.out.open(out_mode, encoding="utf-8") as out_f:
            tasks = [process_item(provider, engine, item, semaphore) for item in remaining]
            for i, coro in enumerate(asyncio.as_completed(tasks), start=1):
                result = await coro
                results.append(result)
                out_f.write(json.dumps(asdict(result)) + "\n")
                out_f.flush()
                if i % 10 == 0 or i == len(remaining):
                    print(f"  {len(done) + i}/{len(items)} done")
    finally:
        await engine.dispose()

    results.sort(key=lambda r: r.idx)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Only run the first N items")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=2,
        help="Groq's free tier throttles on tokens/minute, not request count; keep this low",
    )
    parser.add_argument(
        "--request-interval",
        type=float,
        default=20.0,
        help=(
            "Minimum seconds between dispatching Groq calls, regardless of --concurrency. "
            "gpt-oss-120b's free tier is 8000 tokens/minute; 20s keeps a ~2600-token call "
            "comfortably under that with no reliance on 429 retries."
        ),
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Keep afp.com search results (the answer key); default is a blind run",
    )
    parser.add_argument("--database-url", default=EVAL_DB_URL)
    parser.add_argument(
        "--skip-setup",
        action="store_true",
        help="Reuse an already-migrated-and-seeded --database-url instead of provisioning one",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip items already present in --out (from a prior killed/crashed run) and "
        "append the rest instead of overwriting",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=SCRIPTS_DIR / "eval_results.jsonl",
        help="Per-item results, one JSON object per line (written incrementally as each "
        "item finishes, so a killed run keeps everything scored so far)",
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        default=SCRIPTS_DIR.parent / "EVAL_RESULTS.md",
    )
    args = parser.parse_args()

    if not args.skip_setup:
        print(f"Provisioning eval database at {args.database_url} ...")
        setup_database(args.database_url)

    results = asyncio.run(run(args))
    print(f"{len(results)} per-item results in {args.out}")

    report = build_report(results)
    args.report_out.write_text(report + "\n", encoding="utf-8")
    print(f"Wrote report to {args.report_out}")
    print()
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
