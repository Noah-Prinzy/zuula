"""VectorDbProvider: PgVectorProvider against the real test database, PineconeVectorProvider
against respx mocks of Pinecone's REST API, and the VECTOR_DB_PROVIDER switch. Nothing calls
a real service."""

from datetime import UTC, datetime

import httpx
import pytest
import respx

from app.core import config
from app.db import models as m
from app.providers.embedding import stub_embedding
from app.providers.vector_db import (
    PgVectorProvider,
    PineconeVectorProvider,
    VectorMatch,
    get_vector_db_provider,
)

PINECONE_HOST = "https://index.pinecone.example"
QUERY = f"{PINECONE_HOST}/query"
UPSERT = f"{PINECONE_HOST}/vectors/upsert"


async def _report(db, *, text: str, tracking_id: str, report_id: str) -> m.FactCheckReport:
    db.add(m.Submission(tracking_id=tracking_id, type="text", status="completed"))
    await db.flush()
    report = m.FactCheckReport(
        id=report_id,
        tracking_id=tracking_id,
        title="An existing fact-check",
        content_type="text",
        language="English",
        verdict="false",
        confidence=88,
        summary="Already debunked.",
        category="Politics",
        checked_at=datetime.now(UTC),
        processing_seconds=1.0,
        embedding=stub_embedding(text),
    )
    db.add(report)
    await db.flush()
    return report


# ---- PgVectorProvider ----


async def test_pgvector_finds_the_nearest_report(db):
    text = "Free unlimited internet for every Ugandan starting January 2027."
    report = await _report(db, text=text, tracking_id="ZL-VECA-EF", report_id="fc-2026-8001")

    match = await PgVectorProvider().find_nearest(db, stub_embedding(text))
    assert match is not None
    assert match.report_id == report.id
    assert match.distance == pytest.approx(0.0, abs=1e-6)


async def test_pgvector_returns_none_with_no_embeddings(db):
    match = await PgVectorProvider().find_nearest(db, stub_embedding("anything"))
    assert match is None


async def test_pgvector_find_similar_returns_up_to_limit_closest_first(db):
    closer = await _report(
        db,
        text="Free unlimited internet for every Ugandan.",
        tracking_id="ZL-SIMA-EF",
        report_id="fc-2026-8010",
    )
    farther = await _report(
        db,
        text="A tax increase announced for fuel in 2027.",
        tracking_id="ZL-SIMB-EF",
        report_id="fc-2026-8011",
    )
    query = stub_embedding(
        "Free unlimited internet for every Ugandan starting soon."
    )

    matches = await PgVectorProvider().find_similar(db, query, limit=2)
    assert [m.report_id for m in matches] == [closer.id, farther.id]
    assert matches[0].distance <= matches[1].distance


async def test_pgvector_find_similar_respects_limit(db):
    for i in range(3):
        await _report(
            db,
            text=f"Claim number {i} about something in Uganda.",
            tracking_id=f"ZL-LIM{i + 2}-EF",
            report_id=f"fc-2026-802{i}",
        )
    matches = await PgVectorProvider().find_similar(
        db, stub_embedding("Claim number 0 about something in Uganda."), limit=1
    )
    assert len(matches) == 1


async def test_pgvector_find_similar_with_no_embeddings_returns_empty(db):
    matches = await PgVectorProvider().find_similar(
        db, stub_embedding("anything"), limit=3
    )
    assert matches == []


async def test_pgvector_upsert_is_a_no_op(db):
    # Nothing to assert beyond "doesn't raise" — the embedding is already the
    # fact_check_reports row's own column, written by the INSERT that creates it.
    await PgVectorProvider().upsert(report_id="fc-2026-8002", embedding=[0.1, 0.2])


# ---- PineconeVectorProvider ----


@respx.mock
async def test_pinecone_find_nearest_converts_similarity_to_distance(db):
    respx.post(QUERY).mock(
        return_value=httpx.Response(200, json={"matches": [{"id": "fc-2026-9001", "score": 0.95}]})
    )
    match = await PineconeVectorProvider(api_key="k", host=PINECONE_HOST).find_nearest(
        db, [0.1, 0.2]
    )
    assert match == VectorMatch(report_id="fc-2026-9001", distance=pytest.approx(0.05))


@respx.mock
async def test_pinecone_find_similar_converts_each_match(db):
    respx.post(QUERY).mock(
        return_value=httpx.Response(
            200,
            json={
                "matches": [
                    {"id": "fc-2026-9010", "score": 0.95},
                    {"id": "fc-2026-9011", "score": 0.8},
                ]
            },
        )
    )
    matches = await PineconeVectorProvider(api_key="k", host=PINECONE_HOST).find_similar(
        db, [0.1, 0.2], limit=2
    )
    assert matches == [
        VectorMatch(report_id="fc-2026-9010", distance=pytest.approx(0.05)),
        VectorMatch(report_id="fc-2026-9011", distance=pytest.approx(0.2)),
    ]


@respx.mock
async def test_pinecone_find_similar_on_http_error_returns_empty(db):
    respx.post(QUERY).mock(return_value=httpx.Response(500))
    matches = await PineconeVectorProvider(api_key="k", host=PINECONE_HOST).find_similar(
        db, [0.1, 0.2], limit=2
    )
    assert matches == []


@respx.mock
async def test_pinecone_find_nearest_with_no_matches_returns_none(db):
    respx.post(QUERY).mock(return_value=httpx.Response(200, json={"matches": []}))
    match = await PineconeVectorProvider(api_key="k", host=PINECONE_HOST).find_nearest(
        db, [0.1, 0.2]
    )
    assert match is None


@respx.mock
async def test_pinecone_find_nearest_on_http_error_returns_none(db):
    respx.post(QUERY).mock(return_value=httpx.Response(500))
    match = await PineconeVectorProvider(api_key="k", host=PINECONE_HOST).find_nearest(
        db, [0.1, 0.2]
    )
    assert match is None


@respx.mock
async def test_pinecone_upsert_sends_the_vector():
    route = respx.post(UPSERT).mock(return_value=httpx.Response(200, json={}))
    await PineconeVectorProvider(api_key="k", host=PINECONE_HOST).upsert(
        report_id="fc-2026-9002", embedding=[0.3, 0.4]
    )
    assert route.called
    body = route.calls.last.request.content
    assert b"fc-2026-9002" in body


@respx.mock
async def test_pinecone_upsert_failure_does_not_raise():
    respx.post(UPSERT).mock(return_value=httpx.Response(500))
    # Best effort: a failed index write shouldn't fail the pipeline.
    await PineconeVectorProvider(api_key="k", host=PINECONE_HOST).upsert(
        report_id="fc-2026-9003", embedding=[0.3, 0.4]
    )


# ---- get_vector_db_provider() switch ----


def test_defaults_to_pgvector():
    assert isinstance(get_vector_db_provider(), PgVectorProvider)


def test_unknown_vector_db_provider_raises(monkeypatch):
    monkeypatch.setenv("VECTOR_DB_PROVIDER", "made-up")
    config.get_analysis_settings.cache_clear()
    try:
        with pytest.raises(NotImplementedError):
            get_vector_db_provider()
    finally:
        monkeypatch.delenv("VECTOR_DB_PROVIDER", raising=False)
        config.get_analysis_settings.cache_clear()


def test_pinecone_needs_api_key_and_host(monkeypatch):
    monkeypatch.setenv("VECTOR_DB_PROVIDER", "pinecone")
    config.get_analysis_settings.cache_clear()
    try:
        with pytest.raises(NotImplementedError):
            get_vector_db_provider()
    finally:
        monkeypatch.delenv("VECTOR_DB_PROVIDER", raising=False)
        config.get_analysis_settings.cache_clear()


def test_pinecone_is_used_when_configured(monkeypatch):
    monkeypatch.setenv("VECTOR_DB_PROVIDER", "pinecone")
    monkeypatch.setenv("PINECONE_API_KEY", "k")
    monkeypatch.setenv("PINECONE_HOST", PINECONE_HOST)
    config.get_analysis_settings.cache_clear()
    try:
        assert isinstance(get_vector_db_provider(), PineconeVectorProvider)
    finally:
        monkeypatch.delenv("VECTOR_DB_PROVIDER", raising=False)
        monkeypatch.delenv("PINECONE_API_KEY", raising=False)
        monkeypatch.delenv("PINECONE_HOST", raising=False)
        config.get_analysis_settings.cache_clear()
