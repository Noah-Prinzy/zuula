"""/readyz answers 200 only while PostgreSQL and Redis both do, Brevo takes the key and the
storage bucket answers."""

import json

from app.main import readyz


async def test_ready_when_database_and_redis_answer(db):
    response = await readyz(db)
    assert response.status_code == 200
    assert json.loads(response.body)["checks"] == {"app": "ok", "database": "ok", "redis": "ok"}


async def test_503_names_what_is_down(db, monkeypatch):
    class Down:
        async def ping(self):
            raise ConnectionError("redis is down")

    monkeypatch.setattr("app.main.redis_client.get_async_redis", lambda: Down())
    response = await readyz(db)
    assert response.status_code == 503
    body = json.loads(response.body)
    assert body["status"] == "unavailable" and body["checks"]["redis"] == "unavailable"


async def test_a_rejected_brevo_key_makes_email_unavailable(db, adapter_env, monkeypatch):
    # The bug this guards against: Brevo didn't recognise Render's BREVO_API_KEY, so every
    # sign-in code was refused ("Key not found") while /readyz still said ok.
    import httpx
    import respx

    from app.adapters import email

    adapter_env(BREVO_API_KEY="xsmtpsib-wrong-kind-of-key")
    monkeypatch.setattr("app.main._external_checks", {})
    with respx.mock:
        respx.get(email.BREVO_ACCOUNT_URL).mock(
            return_value=httpx.Response(401, json={"message": "Key not found"})
        )
        response = await readyz(db)
    assert response.status_code == 503
    assert json.loads(response.body)["checks"]["email"] == "unavailable"

    monkeypatch.setattr("app.main._external_checks", {})
    with respx.mock:
        respx.get(email.BREVO_ACCOUNT_URL).mock(return_value=httpx.Response(200, json={}))
        response = await readyz(db)
    assert response.status_code == 200
    assert json.loads(response.body)["checks"]["email"] == "ok"


async def test_a_rejected_storage_key_makes_storage_unavailable(db, monkeypatch):
    # Wrong S3 keys would otherwise surface only when someone's upload fails.
    class Bucket:
        def __init__(self, error=None):
            self.error = error

        async def check(self):
            if self.error:
                raise self.error

    monkeypatch.setattr("app.main._external_checks", {})
    monkeypatch.setattr("app.main.get_object_storage", lambda: Bucket(PermissionError("403")))
    response = await readyz(db)
    assert response.status_code == 503
    assert json.loads(response.body)["checks"]["storage"] == "unavailable"

    monkeypatch.setattr("app.main._external_checks", {})
    monkeypatch.setattr("app.main.get_object_storage", lambda: Bucket())
    response = await readyz(db)
    assert response.status_code == 200
    assert json.loads(response.body)["checks"]["storage"] == "ok"
