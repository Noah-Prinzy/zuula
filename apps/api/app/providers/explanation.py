"""ExplanationGenerator: the Explanation Generator half of §4.1 Layer 3 — turns a claim and
an EvidenceBundle into the report's verdict, claims and citations, in one Groq chat
completion (Llama 3.3 70B, free tier). The bundle's evidence can come from two places, both
composed by app/providers/analysis.py's GroqAnalysisProvider before this module ever sees it:
app/providers/source_verification.py's live Tavily search, and GroqAnalysisProvider's own
local-evidence retrieval against Zuula's verified corpus (docs/adr/0004-ai-engine-retrieval.md)
— `EvidenceBundle.local_evidence_count` says how many of the leading `sources` are the latter,
so this module can label and trust them differently without needing to know where they came
from. Kept in its own module, separate from evidence retrieval, so the Source Verification
Engine and the Explanation Generator are independently testable and swappable, matching the
spec's distinct §4.1 Layer 3 components.

Why one Groq call rather than two (one to cross-reference/score the evidence, one to word
the explanation): Groq's free tier is both rate- and request-limited, and this engine already
spends a Tavily search plus a Groq generation per claim (the P4 cost constraint). A second
LLM call would double per-claim latency and Groq usage for a separation that splitting the
*code* into two modules already gives structurally — the Source Verification Engine's output
(EvidenceBundle) is a normal, independently testable value the Explanation Generator consumes,
with no shared mutable state or hidden coupling between them. Nothing here rules out a second
call later if a real evaluation on labelled data shows the combined call hurts quality enough
to justify the extra cost.
"""

import json
import logging

import httpx

from app.providers.source_verification import EvidenceBundle, is_trusted
from app.schemas.common import CitationStance, ClaimAssessment, Verdict
from app.schemas.fact_check import Citation, Claim

logger = logging.getLogger("zuula.providers.explanation")

_VERDICTS: tuple[Verdict, ...] = (
    "authentic",
    "likely-false",
    "false",
    "ai-generated",
    "unverifiable",
)
_ASSESSMENTS: tuple[ClaimAssessment, ...] = (
    "false",
    "misleading",
    "unsupported",
    "out-of-context",
    "supported",
)
_STANCES: tuple[CitationStance, ...] = ("supports", "contradicts", "context")


class GroqError(Exception):
    pass


class Explanation:
    """The Explanation Generator's output: everything about *wording* a verdict. Dedupe
    (embedding) and the detection signals (ai_signals) are the orchestrator's concern
    (app/providers/analysis.py), not this module's."""

    def __init__(
        self,
        *,
        title: str,
        verdict: str,
        confidence: int,
        summary: str,
        category: str,
        what_is_false: list[str],
        what_is_true: list[str],
        claims: list[Claim],
        citations: list[Citation],
    ):
        self.title = title
        self.verdict = verdict
        self.confidence = confidence
        self.summary = summary
        self.category = category
        self.what_is_false = what_is_false
        self.what_is_true = what_is_true
        self.claims = claims
        self.citations = citations


_SYSTEM_PROMPT = """\
You are Zuula's fact-checking engine for Uganda. You are given a claim (possibly an article \
or a social media post) and a numbered list of evidence. Each item is labeled either \
"(Zuula's own verified fact-check corpus)" — a report on the same or a closely related claim \
that a human fact-checker has already verified, strong evidence — or "(live web search)" — an \
ordinary web result, weigh with normal scrutiny. Weigh the claim against the evidence and \
reply with ONLY a JSON object, no other text, of this exact shape:

{
  "verdict": one of "authentic", "likely-false", "false", "ai-generated", "unverifiable",
  "confidence": integer 0-100,
  "title": a short, neutral title for the claim being checked,
  "summary": 1-3 sentences explaining the verdict,
  "category": a short topic category, e.g. "Health", "Politics", "Economy",
  "whatIsFalse": list of short strings naming what's false (empty if nothing is),
  "whatIsTrue": list of short strings naming what's true or confirmed (can be empty),
  "claims": list of {
    "text": a short quote or paraphrase of the specific factual claim,
    "assessment": one of "false", "misleading", "unsupported", "out-of-context", "supported",
    "reason": 1-2 sentences explaining the assessment,
    "sourceIndexes": list of integers, the 0-based indexes of the evidence items (below) that
      support this assessment; empty if none do
  },
  "citationStances": list of {"index": integer, "stance": one of "supports", "contradicts", \
"context"}, one entry per evidence index you actually cited in "claims"
}

If there is no evidence, or none of it is relevant, say so in "summary" and lean toward
"unverifiable" rather than guessing. Only use the evidence given; never invent URLs or
sources."""


def _sources_block(evidence: EvidenceBundle) -> str:
    if not evidence.sources:
        return "No evidence was found."
    lines = []
    for i, s in enumerate(evidence.sources):
        provenance = (
            "Zuula's own verified fact-check corpus"
            if i < evidence.local_evidence_count
            else "live web search"
        )
        lines.append(
            f"[{i}] ({provenance}) {s.title} "
            f"({s.url}, published {s.published_at or 'date unknown'}): {s.snippet[:500]}"
        )
    return "\n".join(lines)


def _find_span(text: str, snippet: str) -> tuple[int, int]:
    if snippet:
        start = text.find(snippet)
        if start != -1:
            return start, start + len(snippet)
    return 0, len(text)


def _coerce(value: object, allowed: tuple[str, ...], default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


class GroqExplanationGenerator:
    def __init__(
        self,
        *,
        groq_api_key: str,
        groq_api_url: str,
        groq_model: str,
        timeout: float = 30.0,
    ):
        self._groq_api_key = groq_api_key
        self._groq_url = f"{groq_api_url.rstrip('/')}/chat/completions"
        self._groq_model = groq_model
        self._timeout = timeout

    async def generate(
        self, *, content_type: str, text: str, evidence: EvidenceBundle
    ) -> Explanation:
        payload = {
            "model": self._groq_model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Content type: {content_type}\n\nSubmitted content:\n{text}\n\n"
                        f"Evidence:\n{_sources_block(evidence)}"
                    ),
                },
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self._groq_api_key}"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(self._groq_url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise GroqError("Groq chat completion failed.") from exc
        if response.status_code >= 400:
            # Groq's error body (e.g. a 429's "tokens per day" vs. plain per-minute rate-limit
            # message, with its own suggested retry delay) is otherwise discarded; keeping it
            # here is diagnostic only — it changes no verdict/scoring logic, just what callers
            # can see about *why* a call failed.
            raise GroqError(
                f"Groq chat completion failed with HTTP {response.status_code}: {response.text}"
            )
        try:
            content = response.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
        except (KeyError, IndexError, ValueError) as exc:
            raise GroqError("Groq returned something other than the expected JSON.") from exc
        return _parse_explanation(data, text, evidence)


def _parse_explanation(data: dict, text: str, evidence: EvidenceBundle) -> Explanation:
    trusted_set = frozenset(evidence.trusted_domains)
    stance_by_index = {
        int(s["index"]): _coerce(s.get("stance"), _STANCES, "context")
        for s in data.get("citationStances") or []
        if isinstance(s, dict) and isinstance(s.get("index"), int)
    }
    citation_id_by_index: dict[int, str] = {}
    citations: list[Citation] = []
    for index, source in enumerate(evidence.sources):
        if index not in stance_by_index:
            continue  # only cite sources the model actually used
        citation_id = f"s{len(citations) + 1}"
        citation_id_by_index[index] = citation_id
        citations.append(
            Citation(
                id=citation_id,
                source_name=source.title,
                title=source.title,
                url=source.url,
                published_at=source.published_at or "",
                stance=stance_by_index[index],
                trusted=(
                    index < evidence.local_evidence_count or is_trusted(source.url, trusted_set)
                ),
                excerpt=source.snippet[:280] or None,
            )
        )

    claims: list[Claim] = []
    for i, c in enumerate(data.get("claims") or []):
        if not isinstance(c, dict):
            continue
        start, end = _find_span(text, str(c.get("text") or ""))
        citation_ids = [
            citation_id_by_index[idx]
            for idx in c.get("sourceIndexes") or []
            if isinstance(idx, int) and idx in citation_id_by_index
        ]
        claims.append(
            Claim(
                id=f"c{i + 1}",
                start=start,
                end=end,
                assessment=_coerce(c.get("assessment"), _ASSESSMENTS, "unsupported"),
                reason=str(c.get("reason") or ""),
                citation_ids=citation_ids,
            )
        )

    confidence = data.get("confidence")
    confidence = max(0, min(100, int(confidence))) if isinstance(confidence, int | float) else 50

    return Explanation(
        title=str(data.get("title") or "Untitled claim")[:200],
        verdict=_coerce(data.get("verdict"), _VERDICTS, "unverifiable"),
        confidence=confidence,
        summary=str(data.get("summary") or ""),
        category=str(data.get("category") or "General"),
        what_is_false=[str(v) for v in data.get("whatIsFalse") or [] if isinstance(v, str)],
        what_is_true=[str(v) for v in data.get("whatIsTrue") or [] if isinstance(v, str)],
        claims=claims,
        citations=citations,
    )
