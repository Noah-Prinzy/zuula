import pytest

from app.core.config import get_language_settings
from app.providers.language import (
    OTHER,
    PIVOT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    StubLanguageProvider,
    SunbirdLanguageProvider,
    display_name,
    get_language_provider,
    plainly_english,
    resolve_submission_language,
)

# One fixture per supported language, each built from that language's stub markers. These
# test the stub's heuristic, not whether the sentences are good Luganda/Acholi/etc.
FIXTURES = {
    "en": "The minister said that fuel prices will double and this is the plan.",
    "lg": "Gavumenti egamba nti ssente zijja kweyongera, naye era abantu beewuunya.",
    "ach": "Lok man tye ki dano pa gavmen ento pien gin pe gutye.",
    "nyn": "Mbwenu kandi okuruga reero ebeyi nizija kweyongyera ahabwokuba.",
    "teo": "Eong arai itunga ijo kere ebe kotoma.",
}


@pytest.mark.parametrize(("code", "text"), FIXTURES.items())
async def test_stub_detects_each_supported_language(code, text):
    result = await StubLanguageProvider().detect(text=text)
    assert result.language == code
    assert 0.0 < result.confidence <= 1.0
    assert code not in result.also_contains


def test_fixtures_cover_every_supported_language():
    assert set(FIXTURES) == set(SUPPORTED_LANGUAGES)


async def test_stub_detection_is_deterministic():
    provider = StubLanguageProvider()
    assert await provider.detect(text=FIXTURES["lg"]) == await provider.detect(text=FIXTURES["lg"])


async def test_stub_detection_is_case_insensitive():
    provider = StubLanguageProvider()
    assert (await provider.detect(text=FIXTURES["teo"].upper())).language == "teo"


async def test_stub_returns_other_when_nothing_matches():
    result = await StubLanguageProvider().detect(text="Bonjour tout le monde 123")
    assert result.language == OTHER
    assert result.confidence == 0.0
    assert result.also_contains == []


async def test_stub_returns_other_for_empty_text():
    assert (await StubLanguageProvider().detect(text="")).language == OTHER


async def test_stub_reports_code_switching():
    # Mostly Luganda, with some English mixed in.
    text = "Gavumenti egamba nti ssente zijja, naye era the minister is wrong."
    result = await StubLanguageProvider().detect(text=text)
    assert result.language == "lg"
    assert result.also_contains == ["en"]
    assert result.confidence < 1.0


async def test_stub_ties_go_to_the_earlier_language():
    # One English marker, one Luganda marker: English comes first in SUPPORTED_LANGUAGES.
    result = await StubLanguageProvider().detect(text="the nti")
    assert result.language == "en"
    assert result.also_contains == ["lg"]


async def test_stub_translation_to_pivot_is_clearly_marked():
    result = await StubLanguageProvider().translate(
        text=FIXTURES["lg"], source="lg", target=PIVOT_LANGUAGE
    )
    assert result.translated is True
    assert result.text.startswith("[stub-translation lg->en] ")
    assert result.text.endswith(FIXTURES["lg"])
    assert (result.source, result.target) == ("lg", "en")


async def test_stub_translation_back_to_submission_language():
    result = await StubLanguageProvider().translate(
        text="This claim is false.", source=PIVOT_LANGUAGE, target="ach"
    )
    assert result.translated is True
    assert result.text == "[stub-translation en->ach] This claim is false."


async def test_stub_translation_same_language_passes_through():
    result = await StubLanguageProvider().translate(text="Unchanged.", source="en", target="en")
    assert result.translated is False
    assert result.text == "Unchanged."


@pytest.mark.parametrize(("source", "target"), [(OTHER, "en"), ("en", OTHER), ("fr", "en")])
async def test_stub_translation_rejects_unsupported_languages(source, target):
    with pytest.raises(ValueError):
        await StubLanguageProvider().translate(text="x", source=source, target=target)


async def test_resolve_trusts_an_explicit_language_choice():
    # Luganda text, but the submitter said Ateso: their choice wins and detection is skipped.
    assert await resolve_submission_language("teo", FIXTURES["lg"], StubLanguageProvider()) == "teo"


async def test_resolve_detects_when_auto():
    assert await resolve_submission_language("auto", FIXTURES["nyn"], StubLanguageProvider()) == "nyn"


async def test_resolve_can_return_other():
    assert await resolve_submission_language("auto", "Bonjour", StubLanguageProvider()) == OTHER


def test_display_names():
    assert display_name("lg") == "Luganda"
    assert display_name(OTHER) == "Other"


def test_stub_without_a_key(adapter_env):
    assert isinstance(get_language_provider(), StubLanguageProvider)


def test_sunbird_when_the_key_is_set(monkeypatch):
    monkeypatch.setenv("SUNBIRD_API_KEY", "test-key")
    monkeypatch.setenv("SUNBIRD_API_URL", "https://sunbird.example")
    get_language_settings.cache_clear()
    try:
        provider = get_language_provider()
        assert isinstance(provider, SunbirdLanguageProvider)
        # LANGUAGE_PROVIDER=stub still wins over a key.
        monkeypatch.setenv("LANGUAGE_PROVIDER", "stub")
        get_language_settings.cache_clear()
        assert isinstance(get_language_provider(), StubLanguageProvider)
    finally:
        get_language_settings.cache_clear()


@pytest.mark.parametrize("choice", ["sunbird", "google"])
def test_unusable_provider_choices_raise(monkeypatch, choice):
    # `sunbird` without a key, or a provider that doesn't exist.
    monkeypatch.setenv("LANGUAGE_PROVIDER", choice)
    get_language_settings.cache_clear()
    try:
        with pytest.raises(NotImplementedError):
            get_language_provider()
    finally:
        get_language_settings.cache_clear()


# ---- Plainly English text skips detection (Milestone D2b) ----


class _NoDetect(StubLanguageProvider):
    async def detect(self, *, text):
        raise AssertionError("detection should have been skipped")


@pytest.mark.parametrize(
    "text",
    [
        FIXTURES["en"],
        "Museveni said that the roads in Kampala will be repaired by December.",
        "Is it true that the government has banned boda bodas in the city centre?",
    ],
)
async def test_plainly_english_text_is_resolved_without_the_provider(text):
    assert await resolve_submission_language("auto", text, _NoDetect()) == PIVOT_LANGUAGE


@pytest.mark.parametrize(
    "text",
    [
        *(FIXTURES[code] for code in ("lg", "ach", "nyn", "teo")),
        # Luganda quoting English names and a number.
        "Gavumenti egamba nti ssente za bannabyabufuzi zijja kweyongera emirundi esatu omwaka guno.",
        "Abasawo mu ddwaliro ly e Mulago bagamba nti eddagala eppya liwonya omusujja.",
        # Too short to be sure: detection decides.
        "Fuel is the price.",
    ],
)
def test_other_text_is_left_to_detection(text):
    assert not plainly_english(text)


async def test_a_slow_sunbird_call_is_logged(caplog, monkeypatch):
    import httpx
    import respx

    from app.providers import language

    monkeypatch.setattr(language, "_SLOW_SECONDS", -1.0)  # every call counts as slow
    provider = SunbirdLanguageProvider(api_url="https://sunbird.test", api_key="k")
    with respx.mock:
        respx.post("https://sunbird.test/tasks/language_id").mock(
            return_value=httpx.Response(200, json={"language": "lug"})
        )
        assert (await provider.detect(text="Gavumenti egamba")).language == "lg"
    assert "Sunbird /tasks/language_id took" in caplog.text and "(HTTP 200)" in caplog.text
