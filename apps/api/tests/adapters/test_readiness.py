"""ZUULA_ENV=production refuses to start on stub adapters unless they're explicitly allowed,
and the stubs that would be unsafe there are switched off (ADR 0002 §7, §11)."""

import logging

import pytest

from app.adapters import oauth, telegram, whatsapp
from app.adapters.readiness import ADAPTERS, assert_production_ready
from app.core.config import AdaptersSettings, Settings, get_settings

_ALL = {var.lower(): "set" for _, variables in ADAPTERS.values() for var in variables}
_READY = {**_ALL, "africastalking_username": "zuula", "email_smtp_host": "smtp.example.com"}


def _prod(**overrides) -> Settings:
    return Settings(**{"env": "production", "secret_key": "real", **overrides})


def test_development_never_blocks():
    assert_production_ready(Settings(env="development"), AdaptersSettings())


def test_production_names_every_missing_setting():
    with pytest.raises(RuntimeError) as exc:
        assert_production_ready(Settings(env="production"), AdaptersSettings())
    message = str(exc.value)
    for var in (
        "TURNSTILE_SECRET_KEY",
        "CLAMAV_HOST",
        "WHATSAPP_APP_SECRET",
        "TELEGRAM_WEBHOOK_SECRET",
        "ZUULA_SECRET_KEY",
        "ZUULA_ALLOW_STUB_ADAPTERS",
    ):
        assert var in message


def test_production_rejects_the_sms_sandbox():
    with pytest.raises(RuntimeError, match="not 'sandbox'"):
        assert_production_ready(
            _prod(), AdaptersSettings(**{**_ALL, "africastalking_username": "sandbox"})
        )


def test_production_starts_when_everything_is_set():
    assert_production_ready(_prod(), AdaptersSettings(**_READY))


def test_listed_adapters_may_be_stubs_with_a_warning(caplog):
    everything = ",".join(ADAPTERS)
    with caplog.at_level(logging.WARNING, logger="zuula.adapters"):
        assert_production_ready(_prod(allow_stub_adapters=everything), AdaptersSettings())
    assert "WITHOUT" in caplog.text and "WhatsApp" in caplog.text


def test_only_the_listed_adapters_are_excused():
    with pytest.raises(RuntimeError) as exc:
        assert_production_ready(_prod(allow_stub_adapters="whatsapp, telegram"), AdaptersSettings())
    assert "TURNSTILE_SECRET_KEY" in str(exc.value)
    assert "WHATSAPP_APP_SECRET" not in str(exc.value)


def test_the_secret_key_is_never_excused():
    with pytest.raises(RuntimeError, match="ZUULA_SECRET_KEY"):
        assert_production_ready(
            Settings(env="production", allow_stub_adapters=",".join(ADAPTERS)), AdaptersSettings()
        )


def test_unknown_adapter_names_are_refused():
    with pytest.raises(RuntimeError, match="unknown adapters: whatsap"):
        assert_production_ready(_prod(allow_stub_adapters="whatsap"), AdaptersSettings(**_READY))


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setattr(get_settings(), "env", "production")


def test_production_never_signs_in_with_the_stub_oauth(production):
    with pytest.raises(oauth.ProviderUnavailable):
        oauth.get_oauth_provider("google")


def test_production_refuses_unverifiable_webhooks(production):
    assert whatsapp.get_whatsapp_adapter().verify_signature(b"{}", None) is False
    assert telegram.get_telegram_adapter().verify_secret(None) is False
