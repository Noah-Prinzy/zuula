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
    # No transcript: an image is checked on its headline (and, with a vision model, what the
    # image says; the stub reader reads nothing).
    assert report.submitted_text == "A photo"


class _RecordingAnalysisProvider:
    """A fake AnalysisProvider that records what it was handed (app/providers/analysis.py's
    `media` param) and optionally returns a fixed embedding, so tests can see what
    app/worker/pipeline.py passes in without needing GroqAnalysisProvider's real HTTP calls."""

    def __init__(self, embedding=None):
        self.seen = {}
        self._embedding = embedding

    async def analyze(self, *, db, content_type, text, language, media=None):
        from app.providers.analysis import StubAnalysisProvider

        self.seen = {"media": media, "content_type": content_type}
        result = await StubAnalysisProvider().analyze(
            db=db, content_type=content_type, text=text, language=language, media=media
        )
        result.embedding = self._embedding
        return result


async def test_image_media_bytes_are_handed_to_the_analysis_provider(db, monkeypatch):
    key = "submissions/test-image/original"
    StubObjectStorage.OBJECTS[key] = (b"fake-image-bytes", "image/jpeg")
    fields = {
        **validate_input({"type": "media", "headline": "A photo"}),
        "media_object_key": key,
        "media_content_type": "image/jpeg",
    }
    s, _ = await create_submission(db, fields=fields, channel="web")
    await db.commit()

    recording = _RecordingAnalysisProvider()
    monkeypatch.setattr("app.worker.pipeline.get_analysis_provider", lambda: recording)
    await run_pipeline(db, s.tracking_id)

    assert recording.seen == {"media": b"fake-image-bytes", "content_type": "image"}


async def test_a_text_submission_is_never_handed_media_bytes(db, monkeypatch):
    recording = _RecordingAnalysisProvider()
    monkeypatch.setattr("app.worker.pipeline.get_analysis_provider", lambda: recording)
    s = await _submit(db, _INPUT["text"])
    await run_pipeline(db, s.tracking_id)

    assert recording.seen["media"] is None


async def test_a_new_report_with_an_embedding_is_upserted_into_the_vector_db(db, monkeypatch):
    calls = []

    class _RecordingVectorDb:
        async def find_nearest(self, db, embedding):
            return None

        async def upsert(self, *, report_id, embedding):
            calls.append((report_id, embedding))

    from app.providers.embedding import StubEmbeddingProvider

    embedding = StubEmbeddingProvider().embed("Some submitted text long enough to check.")
    monkeypatch.setattr("app.worker.pipeline.get_vector_db_provider", lambda: _RecordingVectorDb())
    monkeypatch.setattr(
        "app.worker.pipeline.get_analysis_provider",
        lambda: _RecordingAnalysisProvider(embedding=embedding),
    )

    s = await _submit(db, _INPUT["text"])
    await run_pipeline(db, s.tracking_id)

    report = (
        await db.scalars(
            select(m.FactCheckReport).where(m.FactCheckReport.tracking_id == s.tracking_id)
        )
    ).one()
    assert calls == [(report.id, embedding)]


async def test_a_report_with_no_embedding_is_not_upserted(db, monkeypatch):
    calls = []

    class _RecordingVectorDb:
        async def find_nearest(self, db, embedding):
            return None

        async def upsert(self, *, report_id, embedding):
            calls.append((report_id, embedding))

    monkeypatch.setattr("app.worker.pipeline.get_vector_db_provider", lambda: _RecordingVectorDb())
    # StubAnalysisProvider (the pipeline's real default here) never fills in an embedding.
    s = await _submit(db, _INPUT["text"])
    await run_pipeline(db, s.tracking_id)

    assert calls == []


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

    async def analyze(self, *, db, content_type, text, language, media=None):
        from app.providers.analysis import StubAnalysisProvider

        self.seen = {"text": text, "language": language}
        return await StubAnalysisProvider().analyze(
            db=db, content_type=content_type, text=text, language=language, media=media
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


# ---- Timing (Milestone D1) and explanation translation (D2) ----


async def test_steps_report_real_time_and_the_verdict_is_reached_in_sources(db, monkeypatch):
    # With no padding (PIPELINE_STEP_SCALE=0, as in production) a step reports how long its
    # work took, not its display estimate; the slow analysis shows up under `sources`.
    import asyncio

    class Slow(_Recording):
        async def analyze(self, **kwargs):
            await asyncio.sleep(0.3)
            return await super().analyze(**kwargs)

    monkeypatch.setattr("app.worker.pipeline.get_analysis_provider", Slow)
    s = await _submit(db, _INPUT["text"])
    await run_pipeline(db, s.tracking_id)
    await db.refresh(s)
    seconds = {step["step"]: step["seconds"] for step in s.steps}
    assert seconds["sources"] >= 0.3
    assert seconds["received"] < 0.3 and seconds["claims"] < 0.3


async def test_an_analysis_outage_fails_at_sources(db, monkeypatch):
    class Down:
        async def analyze(self, **kwargs):
            raise ConnectionError("Groq is down")

    monkeypatch.setattr("app.worker.pipeline.get_analysis_provider", Down)
    s = await _submit(db, _INPUT["text"])
    await run_pipeline(db, s.tracking_id)
    await db.refresh(s)
    assert s.status == "failed"
    assert [step["step"] for step in s.steps] == ["received", "language", "claims"]
    assert s.error["error"] == {
        "code": "server_error",
        "message": "We couldn't check that. Please try again.",
    }


async def test_the_explanation_is_translated_concurrently_once_per_distinct_string():
    import asyncio

    from app.providers.analysis import AnalysisResult
    from app.providers.language import TranslationResult
    from app.worker.pipeline import TRANSLATE_CONCURRENCY, _explain_in

    class Counting:
        def __init__(self):
            self.calls, self.in_flight, self.peak = [], 0, 0

        async def translate(self, *, text, source, target):
            self.calls.append(text)
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)
            await asyncio.sleep(0.01)
            self.in_flight -= 1
            return TranslationResult(
                text=f"lg:{text}", source=source, target=target, translated=True
            )

    analysis = AnalysisResult(
        title="Title",
        verdict="false",
        confidence=80,
        summary="Summary",
        category="politics",
        what_is_false=[f"false {i}" for i in range(6)] + ["Summary"],
        what_is_true=["", "true"],
    )
    languages = Counting()
    out = await _explain_in(analysis, "lg", languages, "ZL-TEST")
    assert sorted(languages.calls) == sorted(
        {"Title", "Summary", "true", *(f"false {i}" for i in range(6))}
    )
    assert 1 < languages.peak <= TRANSLATE_CONCURRENCY
    assert out.title == "lg:Title" and out.what_is_false[-1] == "lg:Summary"
    assert out.what_is_true == ["", "lg:true"]


async def test_a_partial_translation_failure_keeps_the_whole_explanation_in_english():
    from app.providers.analysis import AnalysisResult
    from app.providers.language import TranslationResult
    from app.worker.pipeline import _explain_in

    class Flaky:
        async def translate(self, *, text, source, target):
            if text == "Summary":
                raise ConnectionError("429")
            return TranslationResult(
                text=f"lg:{text}", source=source, target=target, translated=True
            )

    analysis = AnalysisResult(
        title="Title", verdict="false", confidence=80, summary="Summary", category="politics"
    )
    out = await _explain_in(analysis, "lg", Flaky(), "ZL-TEST")
    assert (out.title, out.summary) == ("Title", "Summary")


# ---- Reading images (Milestone D4) ----


def _png() -> bytes:
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(out, "PNG")
    return out.getvalue()


async def _submit_image(db, headline="Is this true?"):
    from app.adapters.storage import StubObjectStorage

    s = await _submit(db, {"type": "media", "headline": headline})
    s.media_object_key, s.media_content_type = f"submissions/{s.tracking_id}/original", "image/png"
    StubObjectStorage.OBJECTS[s.media_object_key] = (_png(), "image/png")
    await db.commit()
    return s


async def test_an_image_is_checked_on_what_it_says(db, monkeypatch):
    from app.providers.image_reader import ImageReading

    class Reader:
        async def read(self, *, image):
            assert image[1:4] == b"PNG"
            return ImageReading(
                text="FREE electricity for all homes",
                claim="Uganda announced free electricity for all homes.",
                description="A blue news graphic.",
            )

    recording = _Recording()
    monkeypatch.setattr("app.worker.pipeline.get_image_reader", Reader)
    monkeypatch.setattr("app.worker.pipeline.get_analysis_provider", lambda: recording)
    s = await _submit_image(db)
    await run_pipeline(db, s.tracking_id)
    checked = recording.seen["text"]
    assert checked.startswith("Is this true?\n\nUganda announced free electricity")
    assert "Text in the image: FREE electricity for all homes" in checked
    report = (
        await db.scalars(
            select(m.FactCheckReport).where(m.FactCheckReport.tracking_id == s.tracking_id)
        )
    ).one()
    assert report.content_type == "image" and report.submitted_text == checked


async def test_an_unreadable_image_is_checked_on_its_headline(db, monkeypatch):
    class Down:
        async def read(self, *, image):
            raise ConnectionError("every vision model failed")

    recording = _Recording()
    monkeypatch.setattr("app.worker.pipeline.get_image_reader", Down)
    monkeypatch.setattr("app.worker.pipeline.get_analysis_provider", lambda: recording)
    s = await _submit_image(db, headline="Fuel prices doubling?")
    await run_pipeline(db, s.tracking_id)
    await db.refresh(s)
    assert s.status == "completed" and recording.seen["text"] == "Fuel prices doubling?"
