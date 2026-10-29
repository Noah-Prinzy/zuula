import json

import httpx
import pytest
import respx

from app.core import config
from app.providers.embedding import (
    EMBEDDING_DIMENSIONS,
    StubEmbeddingProvider,
    get_embedding_provider,
    stub_embedding,
)


def test_stub_is_deterministic_across_instances():
    a = stub_embedding("The minister announced a new policy today.")
    b = stub_embedding("The minister announced a new policy today.")
    assert a == b
    assert len(a) == EMBEDDING_DIMENSIONS


def test_stub_differs_for_unrelated_text():
    a = stub_embedding("Free internet for every Ugandan from January.")
    b = stub_embedding("The president opened a new hospital in Mbale.")
    assert a != b


def test_stub_handles_empty_text():
    assert stub_embedding("") == [0.0] * EMBEDDING_DIMENSIONS


def test_get_embedding_provider_returns_stub_by_default():
    assert isinstance(get_embedding_provider(), StubEmbeddingProvider)


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "made-up")
    config.get_analysis_settings.cache_clear()
    try:
        with pytest.raises(NotImplementedError):
            get_embedding_provider()
    finally:
        monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
        config.get_analysis_settings.cache_clear()
        # Restore tests/conftest.py's fast-pipeline override, which cache_clear() just dropped.
        config.get_analysis_settings().pipeline_step_scale = 0.0


# ---- Hosted model on Hugging Face (Milestone D7) ----

HF = "https://hf.example/hf-inference"
MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
ENDPOINT = f"{HF}/models/{MODEL}/pipeline/feature-extraction"


def _hf():
    from app.providers.embedding import HuggingFaceEmbeddingProvider

    return HuggingFaceEmbeddingProvider(api_url=HF, token="hf_x", model_name=MODEL)


@respx.mock
async def test_huggingface_returns_the_unit_sentence_vector():
    route = respx.post(ENDPOINT).mock(
        return_value=httpx.Response(200, json=[2.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1))
    )
    vector = await _hf().embed("Free electricity for every home")
    assert vector[0] == 1.0 and len(vector) == EMBEDDING_DIMENSIONS
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer hf_x"
    assert json.loads(request.content) == {"inputs": "Free electricity for every home"}


@respx.mock
async def test_huggingface_token_vectors_are_mean_pooled():
    tokens = [[1.0] + [0.0] * 383, [0.0, 1.0] + [0.0] * 382]
    respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=[tokens]))
    vector = await _hf().embed("x")
    assert vector[0] == pytest.approx(vector[1]) and vector[0] == pytest.approx(0.5**0.5)


@pytest.mark.parametrize(
    "answer",
    [httpx.Response(503), httpx.Response(200, json=[0.1] * 768), httpx.Response(200, json={})],
)
@respx.mock
async def test_huggingface_failures_raise_embedding_error(answer):
    from app.providers.embedding import EmbeddingError

    respx.post(ENDPOINT).mock(return_value=answer)
    with pytest.raises(EmbeddingError):
        await _hf().embed("x")


def test_huggingface_without_a_token_falls_back_to_the_stub(monkeypatch):
    from app.providers.embedding import HuggingFaceEmbeddingProvider

    monkeypatch.setenv("EMBEDDING_PROVIDER", "huggingface")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    config.get_analysis_settings.cache_clear()
    try:
        assert isinstance(get_embedding_provider(), StubEmbeddingProvider)
        monkeypatch.setenv("HF_TOKEN", "hf_x")
        config.get_analysis_settings.cache_clear()
        assert isinstance(get_embedding_provider(), HuggingFaceEmbeddingProvider)
    finally:
        monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
        monkeypatch.delenv("HF_TOKEN", raising=False)
        config.get_analysis_settings.cache_clear()
        config.get_analysis_settings().pipeline_step_scale = 0.0


# ---- Gemini embeddings, production's model (Milestone D7) ----

GEMINI = "https://gemini.example/v1beta"


def _gemini():
    from app.providers.embedding import GeminiEmbeddingProvider

    return GeminiEmbeddingProvider(api_url=GEMINI, api_key="g", model_name="gemini-embedding-001")


@respx.mock
async def test_gemini_asks_for_384_dimensions_and_normalises():
    route = respx.post(f"{GEMINI}/models/gemini-embedding-001:embedContent").mock(
        return_value=httpx.Response(
            200, json={"embedding": {"values": [3.0, 4.0] + [0.0] * (EMBEDDING_DIMENSIONS - 2)}}
        )
    )
    vector = await _gemini().embed("Free electricity for every home")
    assert vector[:2] == [0.6, 0.8] and len(vector) == EMBEDDING_DIMENSIONS
    request = route.calls.last.request
    assert request.headers["x-goog-api-key"] == "g"
    assert json.loads(request.content) == {
        "content": {"parts": [{"text": "Free electricity for every home"}]},
        "taskType": "SEMANTIC_SIMILARITY",
        "outputDimensionality": EMBEDDING_DIMENSIONS,
    }


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(429),
        httpx.Response(200, json={"embedding": {"values": [0.1] * 768}}),
        httpx.Response(200, json={"error": "nope"}),
    ],
)
@respx.mock
async def test_gemini_failures_raise_embedding_error(answer):
    from app.providers.embedding import EmbeddingError

    respx.post(f"{GEMINI}/models/gemini-embedding-001:embedContent").mock(return_value=answer)
    with pytest.raises(EmbeddingError):
        await _gemini().embed("x")


def test_gemini_needs_its_key(monkeypatch):
    from app.providers.embedding import GeminiEmbeddingProvider

    monkeypatch.setenv("EMBEDDING_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    config.get_analysis_settings.cache_clear()
    try:
        assert isinstance(get_embedding_provider(), StubEmbeddingProvider)
        monkeypatch.setenv("GEMINI_API_KEY", "g")
        config.get_analysis_settings.cache_clear()
        assert isinstance(get_embedding_provider(), GeminiEmbeddingProvider)
    finally:
        monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        config.get_analysis_settings.cache_clear()
        config.get_analysis_settings().pipeline_step_scale = 0.0
