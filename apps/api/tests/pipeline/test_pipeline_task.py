"""app/worker/pipeline.py's run_pipeline against the real test database (P3): step order per
submission type, the failure path, the report it writes, and what it triggers."""

import pytest
import trafilatura
from sqlalchemy import select

from app.adapters.storage import StubObjectStorage
from app.db import models as m
from app.services.submissions import chat_fields, create_submission, validate_input
from app.worker.pipeline import PIPELINES, run_pipeline

_INPUT = {
    "text": {"type": "text", "content": "Some submitted text long enough to check."},
    "url": {"type": "url", "url": "https://example.com/some-article"},
    "article": {"type": "article", "content": "An article body " * 5, "headline": "Headline"},
    "media": {"type": "media", "headline": "A photo"},
}


@pytest.fixture(autouse=True)
def _mock_article_fetch(monkeypatch):
    """The `fetch` step (app/providers/fetch.py) calls trafilatura, which makes a real HTTP
    request. No test here talks to a real network: by default this fakes a successful
    download+extraction; test_url_with_fail_in_it_fails overrides it with a failure."""
    monkeypatch.setattr(trafilatura, "fetch_url", lambda url: "<html>fetched</html>")
    monkeypatch.setattr(trafilatura, "extract", lambda html, **kwargs: "An extracted article.")


async def _submit(db, body, **kwargs):
    submission, _ = await create_submission(
        db, fields=validate_input(body), channel="web", **kwargs
    )
    await db.commit()
    return submission


@pytest.mark.parametrize("sub_type", sorted(PIPELINES))
async def test_pipeline_runs_expected_steps_and_writes_a_report(db, sub_type):
    s = await _submit(db, _INPUT[sub_type])
    await run_pipeline(db, s.tracking_id)

    await db.refresh(s)
    assert s.status == "completed"
    assert [step["step"] for step in s.steps] == PIPELINES[sub_type]
    assert all(step["status"] == "done" for step in s.steps)
    assert s.completed_at is not None

    report = (
        await db.scalars(
            select(m.FactCheckReport).where(m.FactCheckReport.tracking_id == s.tracking_id)
        )
    ).one()
    assert report.id.startswith("fc-")
    assert report.verdict in ("authentic", "likely-false", "false", "ai-generated", "unverifiable")
    assert report.ccs is None and report.community_status == "standard"


async def test_unknown_submission_is_a_noop(db):
    await run_pipeline(db, "ZL-GONE-22")  # nothing to do, nothing raised


async def test_a_redelivered_task_does_not_run_twice(db):
    s = await _submit(db, _INPUT["text"])
    await run_pipeline(db, s.tracking_id)
    await run_pipeline(db, s.tracking_id)  # Celery redelivery: already completed
    reports = await db.scalars(
        select(m.FactCheckReport).where(m.FactCheckReport.tracking_id == s.tracking_id)
    )
    assert len(reports.all()) == 1


async def test_an_unfetchable_url_fails(db, monkeypatch):
    monkeypatch.setattr(trafilatura, "fetch_url", lambda url: None)
    s = await _submit(db, {"type": "url", "url": "https://example.com/some-article"})
    await run_pipeline(db, s.tracking_id)
    await db.refresh(s)
    assert s.status == "failed"
    assert s.error["error"]["code"] == "invalid_content"
    # "received" ran to completion; "fetch" is where it fails, so it's never a done step.
    assert [step["step"] for step in s.steps] == ["received"]


async def test_a_url_with_no_article_in_it_fails(db, monkeypatch):
    monkeypatch.setattr(trafilatura, "extract", lambda html, **kwargs: None)
    s = await _submit(db, {"type": "url", "url": "https://example.com/some-article"})
    await run_pipeline(db, s.tracking_id)
    await db.refresh(s)
    assert s.status == "failed"
    assert s.error["error"]["code"] == "invalid_content"


# ---- Transcription (`transcribe` step, media submissions) ----


async def test_audio_media_is_transcribed_before_claims(db):
    key = "submissions/test-audio/original"
    StubObjectStorage.OBJECTS[key] = (b"fake-audio-bytes", "audio/mpeg")
    fields = {
        **validate_input({"type": "media", "headline": "A voice note"}),
        "media_object_key": key,
        "media_content_type": "audio/mpeg",
    }
    s, _ = await create_submission(db, fields=fields, channel="web")
    await db.commit()
    await run_pipeline(db, s.tracking_id)

    report = (
        await db.scalars(
            select(m.FactCheckReport).where(m.FactCheckReport.tracking_id == s.tracking_id)
        )
    ).one()
    assert report.submitted_text.startswith("[stub-transcription audio/mpeg]")
    assert report.content_type == "audio"


async def test_image_media_is_never_sent_for_transcription(db):
    s = await _submit(db, _INPUT["media"])
    await run_pipeline(db, s.tracking_id)
    report = (
        await db.scalars(
            select(m.FactCheckReport).where(m.FactCheckReport.tracking_id == s.tracking_id)
        )
    ).one()
    assert report.submitted_text == ""


async def test_signed_in_submitter_is_notified(db):
    s = await _submit(db, _INPUT["text"], user_id="u6")
    await run_pipeline(db, s.tracking_id)
    note = (
        await db.scalars(
            select(m.Notification)
            .where(m.Notification.user_id == "u6", m.Notification.kind == "verdict-ready")
            .order_by(m.Notification.created_at.desc())
        )
    ).first()
    assert note is not None and note.href.startswith("/fact-checks/fc-")


async def test_low_confidence_verdicts_open_a_review_case(db, monkeypatch):
    from app.providers import analysis

    real = analysis.StubAnalysisProvider.analyze

    async def low_confidence(self, **kwargs):
        result = await real(self, **kwargs)
        result.confidence = 42
        return result

    monkeypatch.setattr(analysis.StubAnalysisProvider, "analyze", low_confidence)
    s = await _submit(db, _INPUT["text"])
    await run_pipeline(db, s.tracking_id)
    report = (
        await db.scalars(
            select(m.FactCheckReport).where(m.FactCheckReport.tracking_id == s.tracking_id)
        )
    ).one()
    case = (
        await db.scalars(select(m.ReviewCase).where(m.ReviewCase.report_id == report.id))
    ).one()
    assert case.reason == "low-confidence" and case.status == "open"


async def test_chat_messages_become_submissions():
    assert chat_fields("https://example.com/story")["type"] == "url"
    assert chat_fields("Is it true schools close next week?")["type"] == "text"


# ---- Language (ADR 0003): detect, translate into English, explain back ----

LUGANDA = "Gavumenti egamba nti ssente zijja kweyongera, naye era abantu beewuunya."


class _Recording:
    """The stub, recording what the analysis provider was handed."""

    def __init__(self):
        self.seen = {}

    async def analyze(self, *, db, content_type, text, language):
        from app.providers.analysis import StubAnalysisProvider

        self.seen = {"text": text, "language": language}
        return await StubAnalysisProvider().analyze(
            db=db, content_type=content_type, text=text, language=language
        )


async def test_ugandan_language_text_is_translated_in_and_explained_back(db, monkeypatch):
    recording = _Recording()
    monkeypatch.setattr("app.worker.pipeline.get_analysis_provider", lambda: recording)
    s = await _submit(db, {"type": "text", "content": LUGANDA, "language": "auto"})
    await run_pipeline(db, s.tracking_id)

    report = (await db.scalars(select(m.FactCheckReport).where(m.FactCheckReport.tracking_id == s.tracking_id))).one()
    # Detected as Luganda; the verdict engine read English; the reader gets Luganda back.
    assert report.language == "Luganda"
    assert recording.seen == {"text": f"[stub-translation lg->en] {LUGANDA}", "language": "en"}
    assert report.summary.startswith("[stub-translation en->lg] ")
    assert report.title.startswith("[stub-translation en->lg] ")
    assert all(c["reason"].startswith("[stub-translation en->lg] ") for c in report.claims)
    # What the person submitted is stored as they wrote it.
    assert report.submitted_text == LUGANDA


async def test_english_is_neither_translated_nor_relabelled(db, monkeypatch):
    recording = _Recording()
    monkeypatch.setattr("app.worker.pipeline.get_analysis_provider", lambda: recording)
    text = "The minister said that fuel prices will double and this is the plan."
    s = await _submit(db, {"type": "text", "content": text, "language": "auto"})
    await run_pipeline(db, s.tracking_id)
    report = (await db.scalars(select(m.FactCheckReport).where(m.FactCheckReport.tracking_id == s.tracking_id))).one()
    assert report.language == "English" and recording.seen["text"] == text
    assert "stub-translation" not in report.summary


async def test_a_language_provider_outage_still_produces_a_report(db, monkeypatch):
    class Down:
        async def detect(self, *, text):
            raise ConnectionError("Sunbird is down")

        async def translate(self, **kwargs):
            raise ConnectionError("Sunbird is down")

    monkeypatch.setattr("app.worker.pipeline.get_language_provider", Down)
    s = await _submit(db, {"type": "text", "content": LUGANDA, "language": "lg"})
    await run_pipeline(db, s.tracking_id)
    await db.refresh(s)
    assert s.status == "completed"
    report = (await db.scalars(select(m.FactCheckReport).where(m.FactCheckReport.tracking_id == s.tracking_id))).one()
    # The explicit choice needs no detection; the explanation stays in English.
    assert report.language == "Luganda" and "stub-translation" not in report.summary
