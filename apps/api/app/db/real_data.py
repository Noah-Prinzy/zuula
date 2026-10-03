"""Loads real, human-verified fact-checks from `data/fact-checks/seed/*.json` (repo root) into
`FactCheckReport` schema objects, for `app.db.seed` to insert alongside (or instead of) the
fictional `SAMPLE_REPORTS`.

Source: AFP Fact Check Africa's own ClaimReview data (claim, verdict, headline, publish date,
language, source URL), pulled via Google's Fact Check Tools API — see the PR that added this
module for the collection method and the org-verdict -> Zuula-Verdict mapping. PesaCheck isn't
indexed by that API and its site blocks automated access, so it contributes nothing here.

These reports never went through Zuula's own pipeline or community rating, so several fields
have no real value to carry over — see the comments below for the defaults used instead.
`data/fact-checks/eval/*.json` has the same shape but is a held-out evaluation split and must
never be read by this module.
"""

import json
from pathlib import Path

from app.schemas.common import CitationStance, ClaimAssessment, Verdict
from app.schemas.fact_check import (
    Citation,
    Claim,
    CommunityRating,
    FactCheckReport,
    RatingCounts,
)
from app.services.community import community_score

REPO_ROOT = Path(__file__).resolve().parents[4]
SEED_DATA_DIR = REPO_ROOT / "data" / "fact-checks" / "seed"

_VIDEO_WORDS = ("video", "footage", "clip", "filmed")
_IMAGE_WORDS = ("photo", "image", "picture")

# No numeric confidence comes from the source data (AFP's ClaimReview carries only a textual
# rating); these are editorial defaults reflecting how definitive each rating is.
_CONFIDENCE = {"false": 90, "likely-false": 75, "ai-generated": 85, "unverifiable": 50}

# A claim-span assessment is a different axis from the report-level Verdict; AFP's ClaimReview
# doesn't distinguish them, so each report-level verdict maps to the closest span assessment.
_CLAIM_ASSESSMENT: dict[Verdict, ClaimAssessment] = {
    "false": "false",
    "likely-false": "misleading",
    "ai-generated": "unsupported",
    "unverifiable": "unsupported",
    "authentic": "supported",
}

_CITATION_STANCE: dict[Verdict, CitationStance] = {
    "authentic": "supports",
    "unverifiable": "context",
}


def _tracking_suffix(i: int) -> str:
    """4 letters encoding `i` in base 26 (AAAA, AAAB, …): tracking_id's first segment must
    match `^[A-Z2-9]{4}$` (content.py's `tracking_id` check constraint), which excludes the
    digits 0/1 (too easily confused with O/I) — letters only sidesteps that entirely."""
    chars = []
    for _ in range(4):
        i, rem = divmod(i, 26)
        chars.append(chr(ord("A") + rem))
    return "".join(reversed(chars))


def _content_type(text: str) -> str:
    low = text.lower()
    if any(w in low for w in _VIDEO_WORDS):
        return "video"
    if any(w in low for w in _IMAGE_WORDS):
        return "image"
    return "text"


def _zero_community() -> CommunityRating:
    """Nobody in Zuula's community has rated an imported report — seed with no votes rather
    than fabricating any, matching real_data's only job (import, not simulate engagement)."""
    zero = RatingCounts(public=0, journalist=0, expert=0)
    return CommunityRating(
        accurate=zero, inaccurate=zero, comments=[], score=community_score(zero, zero)
    )


def _to_report(i: int, record: dict) -> FactCheckReport:
    verdict: Verdict = record["verdict"]
    claim = record["claim"]
    report_id = f"fc-real-{i:04d}"
    stance = _CITATION_STANCE.get(verdict, "contradicts")
    return FactCheckReport(
        id=report_id,
        tracking_id=f"ZL-{_tracking_suffix(i)}-RL",
        title=claim,
        content_type=_content_type(f"{claim} {record['summary']}"),
        language=record["language"],
        submitted_text=claim,  # no Zuula submission exists; the claim itself stands in
        source_url=record["source_url"],
        verdict=verdict,
        confidence=_CONFIDENCE[verdict],
        summary=record["summary"],
        what_is_false=[claim] if verdict in ("false", "likely-false", "ai-generated") else [],
        what_is_true=[],
        claims=[
            Claim(
                id="c1",
                start=0,
                end=len(claim),
                assessment=_CLAIM_ASSESSMENT[verdict],
                reason=record["summary"],
                citation_ids=[f"s{j + 1}" for j in range(len(record["citations"]))],
            )
        ],
        citations=[
            Citation(
                id=f"s{j + 1}",
                source_name=record["source_org"],
                title=c["title"],
                url=c["url"],
                published_at=record["published_at"],
                stance=stance,
                trusted=True,
            )
            for j, c in enumerate(record["citations"])
        ],
        ai_signals=[],
        annotations=[],
        human_review=None,  # imported as already-verified; never went through Zuula's own review
        community=_zero_community(),
        category=record["category"],
        checked_at=f"{record['published_at']}T12:00:00+03:00",  # date only; time of day invented
        processing_seconds=0.0,  # never ran through Zuula's own pipeline
    )


def load_real_reports(data_dir: Path = SEED_DATA_DIR) -> list[FactCheckReport]:
    """Every record in `data_dir`'s JSON files, as FactCheckReport schema objects, in a stable
    order (by country then source URL) so report ids are deterministic across runs."""
    records: list[dict] = []
    for path in sorted(data_dir.glob("*.json")):
        records.extend(json.loads(path.read_text()))
    records.sort(key=lambda r: (r["country"], r["source_url"]))
    return [_to_report(i, r) for i, r in enumerate(records, start=1)]
