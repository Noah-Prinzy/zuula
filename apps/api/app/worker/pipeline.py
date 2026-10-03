"""The submission pipeline, persisted in PostgreSQL (P3; ADR 0002 §6). Step sequencing,
timing and event shape still match apps/web/lib/analysis.ts's PIPELINES/STEPS exactly.

`run_pipeline(db, tracking_id)` is the whole pipeline as one async function over a database
session: it reads the committed `submissions` row, runs each step (publishing live progress
over Redis for the SSE endpoint), and on success writes the `fact_check_reports` row, opens a
low-confidence review case if needed, and tells the submitter. The Celery task
`run_submission_pipeline` is a thin wrapper running it on the worker's own connection.

A media upload is read back from object storage and scanned by ClamAV in the "scan" step.
A URL is fetched and its article text extracted in the "fetch" step
(app.providers.fetch, P4); audio/video is transcribed in the "transcribe" step
(app.providers.transcription, P4). The `language` step resolves the submission's language
(app.providers.language, Sunbird AI), text in a Ugandan language is translated into English
before `claims`, and the finished explanation is translated back (FR-EXPLAIN-05). The verdict
itself goes through app.providers.analysis.AnalysisProvider (P4).
"""

import asyncio
import dataclasses
import logging
import time
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.adapters.clamav import get_clamav_scanner
from app.adapters.storage import get_object_storage
from app.adapters.telegram import get_telegram_adapter
from app.adapters.whatsapp import get_whatsapp_adapter
from app.core import rules
from app.core.config import get_analysis_settings, get_database_settings
from app.db.ids import next_report_id
from app.db.models import FactCheckReport, Submission
from app.providers.analysis import AnalysisResult, get_analysis_provider
from app.providers.fetch import FetchError, get_article_fetcher
from app.providers.language import (
    OTHER,
    PIVOT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    LanguageProvider,
    display_name,
    get_language_provider,
    resolve_submission_language,
)
from app.providers.transcription import TranscriptionError, get_transcription_provider
from app.realtime import redis_client
from app.realtime.submissions import publish_done, publish_failed, publish_step
from app.services import escalation, notifications
from app.services.pipeline_steps import PIPELINES, STEP_SECONDS
from app.services.platform_settings import get_platform_settings
from app.services.submissions import status_of
from app.worker import celery_app

logger = logging.getLogger("zuula.worker.pipeline")

__all__ = ["PIPELINES", "STEP_SECONDS", "run_pipeline", "run_submission_pipeline"]

# apps/web/lib/submission.ts's SubmissionType ("text"/"url"/"media"/"article", what the form
# bucketed the input as) isn't the same vocabulary as FactCheckReport.contentType
# ("text"/"url"/"image"/"audio"/"video", what the content actually *is*). An article is
# text; a media upload's kind comes from its (already validated) content type.
_REPORT_CONTENT_TYPE: dict[str, str] = {"text": "text", "url": "url", "article": "text"}


def _report_content_type(s: Submission) -> str:
    if s.type == "media":
        kind = (s.media_content_type or "").partition("/")[0]
        return kind if kind in ("image", "audio", "video") else "image"
    return _REPORT_CONTENT_TYPE[s.type]


def _analysis_text(s: Submission) -> str:
    if s.type == "url":
        return s.url or ""
    return s.content or ""


async def run_pipeline(db: AsyncSession, tracking_id: str) -> None:
    s = await db.get(Submission, tracking_id)
    if s is None or s.status != "queued":
        return  # unknown, or already picked up (a redelivered Celery message)
    r = redis_client.get_redis()
    s.status = "processing"
    await db.commit()

    scale = get_analysis_settings().pipeline_step_scale
    started = time.monotonic()

    languages = get_language_provider()
    text = _analysis_text(s)
    # The submission's language code: the submitter's choice, or detected in the `language`
    # step. Media has no `language` step, so it keeps the choice or OTHER even after
    # transcription — Whisper doesn't tell `run_pipeline` what language it heard.
    lang = s.language if s.language in SUPPORTED_LANGUAGES else OTHER
    # What the claims/sources/ai steps read: the text, in English.
    pivot_text = text

    for step in PIPELINES[s.type]:
        seconds = STEP_SECONDS[step]
        publish_step(r, tracking_id, {"step": step, "status": "active", "seconds": seconds})
        await asyncio.sleep(seconds * scale)

        if step == "language":
            lang = await _resolve_language(s, text, languages)
        elif step == "claims":
            pivot_text = await _to_pivot(s, text, lang, languages)

        failure = None
        if step == "scan" and s.media_object_key:
            failure = await _scan_upload(s)
        elif step == "fetch":
            try:
                text = await get_article_fetcher().fetch(url=s.url or "")
                pivot_text = text
            except FetchError as exc:
                failure = ("invalid_content", str(exc))
        elif step == "transcribe" and _is_spoken_media(s):
            try:
                text = await _transcribe_media(s)
                pivot_text = text
            except TranscriptionError as exc:
                failure = ("invalid_content", str(exc))

        if failure is not None:
            code, message = failure
            s.status = "failed"
            s.completed_at = datetime.now(UTC)
            # SubmissionStatusResponse.error embeds the whole ErrorEnvelope.
            s.error = {"error": {"code": code, "message": message}}
            await db.commit()
            publish_failed(r, tracking_id, await status_of(db, s))
            await _reply_on_channel(s, f"We couldn't check that. {message}")
            return

        # Reassign rather than append: JSONB mutation isn't tracked in place.
        s.steps = [*s.steps, {"step": step, "status": "done", "seconds": seconds}]
        await db.commit()
        publish_step(r, tracking_id, {"step": step, "status": "done", "seconds": seconds})

    report_content_type = _report_content_type(s)
    try:
        analysis = await get_analysis_provider().analyze(
            db=db, content_type=report_content_type, text=pivot_text, language=PIVOT_LANGUAGE
        )
    except Exception:  # noqa: BLE001 — Groq/Tavily down: fail closed, same as `_scan_upload`
        logger.exception("Analysis failed for %s", s.tracking_id)
        message = "We couldn't check that. Please try again."
        s.status = "failed"
        s.completed_at = datetime.now(UTC)
        s.error = {"error": {"code": "server_error", "message": message}}
        await db.commit()
        publish_failed(r, tracking_id, await status_of(db, s))
        await _reply_on_channel(s, message)
        return
    # FR-EXPLAIN-05: the explanation comes back in the submission's own language.
    analysis = await _explain_in(analysis, lang, languages, tracking_id)
    now = datetime.now(UTC)
    report = FactCheckReport(
        id=await next_report_id(db, now=now),
        tracking_id=tracking_id,
        title=analysis.title,
        content_type=report_content_type,
        language=display_name(lang),
        submitted_text=text,
        source_url=s.url or s.article_url,
        verdict=analysis.verdict,
        confidence=analysis.confidence,
        summary=analysis.summary,
        what_is_false=analysis.what_is_false,
        what_is_true=analysis.what_is_true,
        claims=[
            c.model_dump(by_alias=True, mode="json", exclude_none=True) for c in analysis.claims
        ],
        citations=[
            c.model_dump(by_alias=True, mode="json", exclude_none=True) for c in analysis.citations
        ],
        ai_signals=[
            a.model_dump(by_alias=True, mode="json", exclude_none=True) for a in analysis.ai_signals
        ],
        category=analysis.category,
        checked_at=now,
        processing_seconds=round(time.monotonic() - started, 2),
        community_status="standard",
        embedding=analysis.embedding,
    )
    db.add(report)
    s.status = "completed"
    s.completed_at = now
    await db.flush()

    if report.confidence < rules.LOW_CONFIDENCE_THRESHOLD:
        await escalation.open_case(db, report, "low-confidence", await get_platform_settings(db))
    if s.user_id:
        notifications.notify(
            db,
            user_id=s.user_id,
            kind="verdict-ready",
            title="Your submission was checked",
            body=f"{report.title} — {notifications.VERDICT_LABELS[report.verdict]}.",
            href=f"/fact-checks/{report.id}",
        )
    await db.commit()

    publish_done(r, tracking_id, await status_of(db, s))
    await _reply_on_channel(
        s,
        f"Zuula verdict: {notifications.VERDICT_LABELS[report.verdict]}. {report.summary} "
        f"Full report: https://zuula.ug/fact-checks/{report.id}",
    )


async def _resolve_language(s: Submission, text: str, languages: LanguageProvider) -> str:
    """The `language` step. A URL's own text isn't fetched yet (P4), so only an explicit
    choice can say what language it's in. A detection failure isn't fatal: the submission is
    analysed as it is, and the report says "Other"."""
    if s.type == "url":
        return s.language if s.language in SUPPORTED_LANGUAGES else OTHER
    try:
        return await resolve_submission_language(s.language, text, languages)
    except Exception:  # noqa: BLE001 — the provider is down or refused: analyse untranslated
        logger.warning("Language detection failed for %s", s.tracking_id, exc_info=True)
        return OTHER


async def _to_pivot(s: Submission, text: str, lang: str, languages: LanguageProvider) -> str:
    """Before `claims`: Luganda, Acholi, Runyankole or Ateso text into English, which the
    claims/sources/ai steps work in. English and OTHER pass through; so does a URL, whose
    content isn't fetched yet. If translation fails, the original text is analysed."""
    if s.type not in ("text", "article") or lang in (PIVOT_LANGUAGE, OTHER) or not text:
        return text
    try:
        result = await languages.translate(text=text, source=lang, target=PIVOT_LANGUAGE)
    except Exception:  # noqa: BLE001
        logger.warning("Translating %s into English failed", s.tracking_id, exc_info=True)
        return text
    return result.text


async def _explain_in(
    analysis: AnalysisResult, lang: str, languages: LanguageProvider, tracking_id: str
) -> AnalysisResult:
    """FR-EXPLAIN-05: the report's own words (title, summary, what's false/true, each claim's
    reason) translated from English into the submission's language. Citation titles stay
    as their sources wrote them. On failure the English explanation is kept."""
    if lang in (PIVOT_LANGUAGE, OTHER):
        return analysis

    async def tr(value: str) -> str:
        if not value:
            return value
        result = await languages.translate(text=value, source=PIVOT_LANGUAGE, target=lang)
        return result.text

    try:
        title = await tr(analysis.title)
        summary = await tr(analysis.summary)
        what_is_false = [await tr(v) for v in analysis.what_is_false]
        what_is_true = [await tr(v) for v in analysis.what_is_true]
        claims = [c.model_copy(update={"reason": await tr(c.reason)}) for c in analysis.claims]
    except Exception:  # noqa: BLE001
        logger.warning("Translating %s's explanation failed", tracking_id, exc_info=True)
        return analysis
    return dataclasses.replace(
        analysis,
        title=title,
        summary=summary,
        what_is_false=what_is_false,
        what_is_true=what_is_true,
        claims=claims,
    )


async def _scan_upload(s: Submission) -> tuple[str, str] | None:
    """The "scan" step: ClamAV over the uploaded bytes. Fails closed — a file that can't be
    scanned isn't analysed. An infected file is deleted straight away."""
    storage = get_object_storage()
    try:
        data = await storage.get(key=s.media_object_key)
        result = await get_clamav_scanner().scan(data)
    except Exception:  # noqa: BLE001 — storage or scanner down: fail closed
        logger.exception("Malware scan failed for %s", s.tracking_id)
        return ("server_error", "We couldn't scan that file for malware. Please try again.")
    if result.clean:
        return None
    logger.warning("Upload %s failed the malware scan: %s", s.tracking_id, result.signature)
    await storage.delete(key=s.media_object_key)
    s.media_object_key = None
    return ("invalid_content", "That file failed our malware scan, so we didn't check it.")


def _is_spoken_media(s: Submission) -> bool:
    """Whether the `transcribe` step has anything to do. The "media" pipeline runs the same
    steps for images, audio and video alike (apps/web/lib/analysis.ts's PIPELINES); an image
    has no speech, so it passes through untouched rather than calling Whisper on it."""
    return (s.media_content_type or "").partition("/")[0] in ("audio", "video")


async def _transcribe_media(s: Submission) -> str:
    """The `transcribe` step for audio/video: the uploaded bytes, through Whisper. Fails
    closed — a submission that can't be transcribed has nothing for `claims`/`sources`/`ai`
    to work with, so it isn't analysed."""
    if not s.media_object_key:
        raise TranscriptionError("That upload is no longer available to transcribe.")
    try:
        data = await get_object_storage().get(key=s.media_object_key)
    except Exception as exc:  # noqa: BLE001 — storage down: fail closed, same as `_scan_upload`
        logger.exception("Couldn't read upload %s to transcribe it", s.tracking_id)
        raise TranscriptionError("We couldn't read that upload to transcribe it.") from exc
    return await get_transcription_provider().transcribe(
        audio=data, content_type=s.media_content_type or ""
    )


async def _reply_on_channel(s: Submission, text: str) -> None:
    """FR-SUBMIT-04: a chat submission gets its answer back in the same chat. Best effort:
    the verdict is already saved, so a failed reply is logged, not retried."""
    if not s.channel_ref:
        return
    try:
        if s.channel == "whatsapp":
            await get_whatsapp_adapter().send_reply(to=s.channel_ref, text=text)
        elif s.channel == "telegram":
            await get_telegram_adapter().send_reply(chat_id=s.channel_ref, text=text)
    except Exception:  # noqa: BLE001
        logger.warning("Couldn't send the verdict back on %s", s.channel, exc_info=True)


async def _run_in_worker(tracking_id: str) -> None:
    engine = create_async_engine(get_database_settings().database_url, poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            await run_pipeline(db, tracking_id)
    finally:
        await engine.dispose()


@celery_app.task(name="zuula.run_submission_pipeline")
def run_submission_pipeline(tracking_id: str) -> None:
    # One event loop and one connection per submission: the worker is a plain process, and
    # asyncpg connections belong to the loop that opened them.
    asyncio.run(_run_in_worker(tracking_id))
