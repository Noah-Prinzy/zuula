"""Every route below is hit through openapi_core's FastAPI middleware, which validates both
the request and the response against apps/api/openapi.yaml and raises on any mismatch. If a
test here fails, either the code doesn't match the contract or the contract doesn't match the
code — both are bugs. This is the check Step 1 promised: "every endpoint returns stub data
that validates against openapi.yaml."

Fixtures (a real database per test, real sign-in sessions per role) are in conftest.py.
"""

import re
from urllib.parse import parse_qs, urlparse

import pytest
import trafilatura
from starlette.testclient import TestClient

from app.adapters import email
from app.main import app as _app
from tests.contract.conftest import (
    ADMIN,
    EXPERT,
    JOURNALIST,
    PARTNER_KEY,
    PUBLIC,
    SAMPLE_PASSWORD,
)


def latest_code(outbox) -> str:
    """The 6-digit code in the most recent stub email/SMS (app/adapters/*.OUTBOX)."""
    message = outbox[-1]
    return re.search(r"\b(\d{6})\b", message.get("body") or message.get("message")).group(1)


REPORT_IDS = [
    "fc-2026-0142",
    "fc-2026-0157",
    "fc-2026-0161",
    "fc-2026-0156",  # authentic verdict, exercises a different code path
    "fc-2026-0158",  # unverifiable verdict, no claims
]


class TestPublicCore:
    def test_search(self, core_client):
        r = core_client.get("/api/v1/fact-checks", params={"q": "internet"})
        assert r.status_code == 200

    def test_search_all_sorts(self, core_client):
        for sort in ("relevance", "newest", "most-rated"):
            r = core_client.get("/api/v1/fact-checks", params={"sort": sort})
            assert r.status_code == 200, sort

    def test_facets(self, core_client):
        assert core_client.get("/api/v1/fact-checks/facets").status_code == 200

    def test_home_feed(self, core_client):
        assert core_client.get("/api/v1/fact-checks/home-feed").status_code == 200

    @pytest.mark.parametrize("report_id", REPORT_IDS)
    def test_get_fact_check(self, core_client, report_id):
        r = core_client.get(f"/api/v1/fact-checks/{report_id}")
        assert r.status_code == 200, r.text

    @pytest.mark.parametrize("report_id", REPORT_IDS)
    def test_related(self, core_client, report_id):
        r = core_client.get(f"/api/v1/fact-checks/{report_id}/related")
        assert r.status_code == 200, r.text

    def test_get_fact_check_not_found(self, core_client):
        assert core_client.get("/api/v1/fact-checks/does-not-exist").status_code == 404

    def test_comments(self, core_client):
        r = core_client.get("/api/v1/fact-checks/fc-2026-0142/comments")
        assert r.status_code == 200, r.text


class TestAuth:
    def test_sign_up(self, core_client):
        r = core_client.post(
            "/api/v1/auth/sign-up",
            json={"name": "Test User", "identifier": "test@example.com", "password": "x" * 12, "consent": True},
        )
        assert r.status_code == 202

    def test_sign_in_public(self, core_client):
        r = core_client.post(
            "/api/v1/auth/sign-in",
            json={"identifier": "amina@example.com", "password": SAMPLE_PASSWORD},
        )
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "public"

    def test_sign_in_needs_two_factor(self, core_client):
        r = core_client.post(
            "/api/v1/auth/sign-in",
            json={"identifier": "david@example.com", "password": SAMPLE_PASSWORD},
        )
        assert r.status_code == 200
        assert r.json()["challengeId"]

    def test_sign_in_unauthorized(self, core_client):
        r = core_client.post("/api/v1/auth/sign-in", json={"identifier": "", "password": ""})
        assert r.status_code == 401

    def test_two_factor_verify(self, core_client):
        challenge = core_client.post(
            "/api/v1/auth/sign-in",
            json={"identifier": "mary@example.com", "password": SAMPLE_PASSWORD},
        ).json()
        r = core_client.post(
            "/api/v1/auth/two-factor/verify",
            json={"challengeId": challenge["challengeId"], "code": latest_code(email.OUTBOX)},
        )
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "admin"

    def test_forgot_password(self, core_client):
        r = core_client.post("/api/v1/auth/forgot-password", json={"identifier": "a@b.com"})
        assert r.status_code == 202

    def test_reset_password(self, core_client):
        core_client.post("/api/v1/auth/forgot-password", json={"identifier": "amina@example.com"})
        r = core_client.post(
            "/api/v1/auth/reset-password",
            json={
                "identifier": "amina@example.com",
                "code": latest_code(email.OUTBOX),
                "password": "x" * 12,
            },
        )
        assert r.status_code == 200

    def test_reset_password_wrong_code(self, core_client):
        r = core_client.post(
            "/api/v1/auth/reset-password",
            json={"identifier": "a@b.com", "code": "123456", "password": "x" * 12},
        )
        assert r.status_code == 400

    def test_two_factor_resend(self, core_client):
        r = core_client.post("/api/v1/auth/two-factor/resend", json={"challengeId": "tfc_admin"})
        assert r.status_code == 202

    def test_oauth_start_redirects_to_provider(self, core_client):
        r = core_client.get("/api/v1/auth/oauth/google/start", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"].startswith("https://google.example/")

    def test_oauth_start_unknown_provider(self, core_client):
        # openapi.yaml constrains {provider} to enum [google, facebook], so openapi-core
        # itself rejects anything else before the request reaches app.core.errors' own
        # not_found check (which exists for a raw, non-contract-validated caller).
        r = core_client.get("/api/v1/auth/oauth/unknown/start", follow_redirects=False)
        assert r.status_code == 400

    def test_oauth_callback_redirects(self, core_client):
        start = core_client.get(
            "/api/v1/auth/oauth/facebook/start", params={"next": "/account"}, follow_redirects=False
        )
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        r = core_client.get(
            "/api/v1/auth/oauth/facebook/callback",
            params={"code": "stub-code", "state": state},
            follow_redirects=False,
        )
        assert r.status_code == 302
        assert r.headers["location"].endswith("/account")
        assert r.cookies.get("zuula_session")

    def test_sign_out(self, core_client):
        assert core_client.post("/api/v1/auth/sign-out").status_code == 204


class TestAccount:
    def test_me_requires_auth(self, core_client):
        assert core_client.get("/api/v1/me").status_code == 401

    def test_me(self, core_client):
        r = core_client.get("/api/v1/me", headers=PUBLIC)
        assert r.status_code == 200

    def test_update_me(self, core_client):
        r = core_client.patch("/api/v1/me", json={"name": "New Name"}, headers=PUBLIC)
        assert r.status_code == 200

    def test_change_password(self, core_client):
        r = core_client.post(
            "/api/v1/me/password",
            json={"currentPassword": SAMPLE_PASSWORD, "newPassword": "x" * 12},
            headers=PUBLIC,
        )
        assert r.status_code == 200

    def test_sessions(self, core_client):
        assert core_client.get("/api/v1/me/sessions", headers=PUBLIC).status_code == 200

    def test_revoke_session(self, core_client):
        assert core_client.delete("/api/v1/me/sessions/d1", headers=PUBLIC).status_code == 204

    def test_data_export(self, core_client):
        assert core_client.get("/api/v1/me/data-export", headers=PUBLIC).status_code == 200

    def test_verification(self, core_client):
        assert core_client.get("/api/v1/me/verification", headers=PUBLIC).status_code == 200

    def test_my_submissions(self, core_client):
        assert core_client.get("/api/v1/me/submissions", headers=PUBLIC).status_code == 200

    def test_my_ratings(self, core_client):
        assert core_client.get("/api/v1/me/ratings", headers=PUBLIC).status_code == 200

    def test_api_usage(self, core_client):
        assert core_client.get("/api/v1/me/api-usage", headers=PUBLIC).status_code == 200


class TestApiKeys:
    def test_forbidden_for_public(self, core_client):
        assert core_client.get("/api/v1/me/api-keys", headers=PUBLIC).status_code == 403

    def test_list(self, core_client):
        assert core_client.get("/api/v1/me/api-keys", headers=JOURNALIST).status_code == 200

    def test_create(self, core_client):
        r = core_client.post(
            "/api/v1/me/api-keys", json={"name": "x", "scopes": ["read"]}, headers=JOURNALIST
        )
        assert r.status_code == 201

    def test_revoke(self, core_client):
        assert core_client.delete("/api/v1/me/api-keys/k1", headers=JOURNALIST).status_code == 204


ANON_SUBMISSION = {"type": "text", "content": "x" * 30, "captchaToken": "stub-token"}


class TestSubmissions:
    def test_create(self, core_client):
        r = core_client.post("/api/v1/submissions", json=ANON_SUBMISSION)
        assert r.status_code == 202
        assert r.json()["trackingId"]

    def test_create_anonymous_without_captcha_rejected(self, core_client):
        # FR-AUTH-07: no captchaToken and no one signed in (core_client's placeholder
        # sessionAuth cookie satisfies openapi-core's presence check but isn't a real session,
        # so app.core.security.get_current_user sees no one).
        r = core_client.post("/api/v1/submissions", json={"type": "text", "content": "x" * 30})
        assert r.status_code == 400

    def test_create_signed_in_without_captcha_ok(self, core_client):
        r = core_client.post(
            "/api/v1/submissions", json={"type": "text", "content": "x" * 30}, headers=PUBLIC
        )
        assert r.status_code == 202

    def test_status(self, core_client):
        # Celery runs eagerly in tests (tests/conftest.py) with pipeline_step_scale=0, so by
        # the time create_submission() returns, the pipeline has already run to completion.
        created = core_client.post("/api/v1/submissions", json=ANON_SUBMISSION).json()
        r = core_client.get(f"/api/v1/submissions/{created['trackingId']}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "completed"
        assert body["result"]["trackingId"] == created["trackingId"]

    def test_status_not_found(self, core_client):
        # Valid TrackingId shape (^ZL-[A-Z2-9]{4}-[A-Z2-9]{2}$, excludes only 0/1) but a
        # tracking id nothing ever submitted.
        assert core_client.get("/api/v1/submissions/ZL-9999-99").status_code == 404

    def test_events_replays_to_done(self, core_client):
        created = core_client.post("/api/v1/submissions", json=ANON_SUBMISSION).json()
        r = core_client.get(f"/api/v1/submissions/{created['trackingId']}/events")
        assert r.status_code == 200
        assert "event: done" in r.text
        assert r.text.count("event: step") == 6  # text pipeline: received/language/claims/sources/ai/report

    def test_an_unfetchable_url_fails(self, core_client, monkeypatch):
        # The `fetch` step (app/providers/fetch.py) calls trafilatura, which makes a real HTTP
        # request. No test here talks to a real network.
        monkeypatch.setattr(trafilatura, "fetch_url", lambda url: None)
        created = core_client.post(
            "/api/v1/submissions",
            json={
                "type": "url",
                "url": "https://example.com/some-article",
                "captchaToken": "stub-token",
            },
        ).json()
        r = core_client.get(f"/api/v1/submissions/{created['trackingId']}")
        assert r.json()["status"] == "failed"


class TestWebhooks:
    # These two go through a plain, unvalidated client rather than core_client: openapi-core's
    # Starlette path/parameter matching mishandles a literal "." in a query parameter name
    # (confirmed in isolation — a `hub_mode` alias validates fine through the same middleware,
    # `hub.mode` always 400s before the request even reaches the route). Meta's real Cloud API
    # sends exactly hub.mode/hub.verify_token/hub.challenge, so the contract keeps those names
    # rather than working around the test tool; only these two tests can't use the contract-
    # validating client. The request/response shape is still declared in openapi.yaml and
    # still worth getting right — it just can't be checked by this particular library today.
    def test_whatsapp_verify_matching_token(self, adapter_env):
        adapter_env(WHATSAPP_VERIFY_TOKEN="verify-me")
        client = TestClient(_app, base_url="https://zuula.ug")
        r = client.get(
            "/webhooks/whatsapp",
            params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "c123"},
        )
        assert r.status_code == 200
        assert r.text == "c123"

    def test_whatsapp_verify_needs_a_configured_token(self):
        # With no WHATSAPP_VERIFY_TOKEN set, an empty token must not match.
        client = TestClient(_app, base_url="https://zuula.ug")
        r = client.get(
            "/webhooks/whatsapp",
            params={"hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "c123"},
        )
        assert r.status_code == 403

    def test_whatsapp_verify_wrong_token(self):
        client = TestClient(_app, base_url="https://zuula.ug")
        r = client.get(
            "/webhooks/whatsapp",
            params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "c123"},
        )
        assert r.status_code == 403

    def test_whatsapp_receive_message(self, core_client):
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {"from": "256700000000", "text": {"body": "Is this claim true?"}}
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        r = core_client.post("/webhooks/whatsapp", json=payload)
        assert r.status_code == 200

    def test_telegram_receive_message(self, core_client):
        payload = {"message": {"chat": {"id": 42}, "text": "Is this claim true?"}}
        r = core_client.post("/webhooks/telegram", json=payload)
        assert r.status_code == 200


class TestRatings:
    def test_rate(self, core_client):
        r = core_client.post(
            "/api/v1/fact-checks/fc-2026-0142/ratings", json={"vote": "accurate"}, headers=PUBLIC
        )
        assert r.status_code == 200

    def test_retract(self, core_client):
        r = core_client.delete("/api/v1/fact-checks/fc-2026-0142/ratings", headers=PUBLIC)
        assert r.status_code == 200

    def test_add_comment(self, core_client):
        r = core_client.post(
            "/api/v1/fact-checks/fc-2026-0142/comments",
            json={"vote": "accurate", "body": "a test comment"},
            headers=PUBLIC,
        )
        assert r.status_code == 201

    def test_report_issue(self, core_client):
        r = core_client.post(
            "/api/v1/fact-checks/fc-2026-0142/report-issue", json={"reason": "test"}, headers=PUBLIC
        )
        assert r.status_code == 202


class TestReview:
    def test_forbidden_for_public(self, core_client):
        assert core_client.get("/api/v1/review/overview", headers=PUBLIC).status_code == 403

    def test_overview(self, core_client):
        assert core_client.get("/api/v1/review/overview", headers=EXPERT).status_code == 200

    def test_queue(self, core_client):
        assert core_client.get("/api/v1/review/queue", headers=EXPERT).status_code == 200

    def test_queue_filtered(self, core_client):
        r = core_client.get("/api/v1/review/queue", params={"assignee": "unassigned"}, headers=EXPERT)
        assert r.status_code == 200

    def test_case(self, core_client):
        r = core_client.get("/api/v1/review/cases/rc-0418", headers=EXPERT)
        assert r.status_code == 200

    def test_case_not_found(self, core_client):
        assert core_client.get("/api/v1/review/cases/nope", headers=EXPERT).status_code == 404

    def test_assign(self, core_client):
        r = core_client.post("/api/v1/review/cases/rc-0418/assign", json={}, headers=EXPERT)
        assert r.status_code == 200

    def test_decision_confirmed(self, core_client):
        r = core_client.post(
            "/api/v1/review/cases/rc-0418/decision",
            json={"outcome": "confirmed", "justification": "matches ground truth"},
            headers=EXPERT,
        )
        assert r.status_code == 200

    def test_decision_overridden(self, core_client):
        r = core_client.post(
            "/api/v1/review/cases/rc-0417/decision",
            json={"outcome": "overridden", "verdict": "likely-false", "justification": "context needed"},
            headers=EXPERT,
        )
        assert r.status_code == 200

    def test_history(self, core_client):
        assert core_client.get("/api/v1/review/history", headers=EXPERT).status_code == 200


class TestNotifications:
    def test_list(self, core_client):
        assert core_client.get("/api/v1/notifications", headers=PUBLIC).status_code == 200

    def test_mark_read(self, core_client):
        assert core_client.post("/api/v1/notifications/n1/read", headers=PUBLIC).status_code == 204

    def test_mark_all_read(self, core_client):
        assert core_client.post("/api/v1/notifications/read-all", headers=PUBLIC).status_code == 204

    def test_alert_settings_get(self, core_client):
        assert core_client.get("/api/v1/me/alert-settings", headers=PUBLIC).status_code == 200

    def test_alert_settings_patch(self, core_client):
        r = core_client.patch(
            "/api/v1/me/alert-settings", json={"topics": ["Health"]}, headers=PUBLIC
        )
        assert r.status_code == 200

    def test_stream(self, core_client):
        r = core_client.get("/api/v1/notifications/stream", headers=PUBLIC)
        assert r.status_code == 200
        assert "event: notification" in r.text


class TestAdmin:
    def test_forbidden_for_expert(self, core_client):
        assert core_client.get("/api/v1/admin/overview", headers=EXPERT).status_code == 403

    def test_overview(self, core_client):
        assert core_client.get("/api/v1/admin/overview", headers=ADMIN).status_code == 200

    def test_users(self, core_client):
        assert core_client.get("/api/v1/admin/users", headers=ADMIN).status_code == 200

    def test_users_filtered(self, core_client):
        r = core_client.get("/api/v1/admin/users", params={"role": "admin", "q": "mary"}, headers=ADMIN)
        assert r.status_code == 200

    def test_update_user(self, core_client):
        r = core_client.patch("/api/v1/admin/users/u1", json={"status": "active"}, headers=ADMIN)
        assert r.status_code == 200

    def test_update_user_not_found(self, core_client):
        r = core_client.patch("/api/v1/admin/users/does-not-exist", json={}, headers=ADMIN)
        assert r.status_code == 404

    def test_moderation_reports(self, core_client):
        assert core_client.get("/api/v1/admin/moderation/reports", headers=ADMIN).status_code == 200

    def test_resolve_report(self, core_client):
        r = core_client.post(
            "/api/v1/admin/moderation/reports/cr1/resolve", json={"action": "dismiss"}, headers=ADMIN
        )
        assert r.status_code == 200

    def test_moderation_signals(self, core_client):
        assert core_client.get("/api/v1/admin/moderation/signals", headers=ADMIN).status_code == 200

    def test_sources(self, core_client):
        assert core_client.get("/api/v1/admin/sources", headers=ADMIN).status_code == 200

    def test_add_source(self, core_client):
        r = core_client.post(
            "/api/v1/admin/sources",
            json={"name": "X", "domain": "x.com", "type": "media", "languages": ["English"], "tier": 1},
            headers=ADMIN,
        )
        assert r.status_code == 201

    def test_update_source(self, core_client):
        r = core_client.patch(
            "/api/v1/admin/sources/s1",
            json={"name": "X", "domain": "x.com", "type": "media", "languages": ["English"], "tier": 1},
            headers=ADMIN,
        )
        assert r.status_code == 200

    def test_remove_source(self, core_client):
        assert core_client.delete("/api/v1/admin/sources/s1", headers=ADMIN).status_code == 204

    def test_broadcasts(self, core_client):
        assert core_client.get("/api/v1/admin/broadcasts", headers=ADMIN).status_code == 200

    def test_send_broadcast(self, core_client):
        r = core_client.post(
            "/api/v1/admin/broadcasts",
            json={
                "title": "t",
                "message": "m",
                "severity": "high",
                "audience": "Everyone",
                "channels": ["in-app"],
            },
            headers=ADMIN,
        )
        assert r.status_code == 202

    def test_monthly_reports(self, core_client):
        assert core_client.get("/api/v1/admin/reports", headers=ADMIN).status_code == 200

    def test_audit_log(self, core_client):
        assert core_client.get("/api/v1/admin/audit-log", headers=ADMIN).status_code == 200

    def test_audit_log_filtered(self, core_client):
        r = core_client.get(
            "/api/v1/admin/audit-log", params={"actorRole": "admin"}, headers=ADMIN
        )
        assert r.status_code == 200

    def test_settings_get(self, core_client):
        assert core_client.get("/api/v1/admin/settings", headers=ADMIN).status_code == 200

    def test_settings_patch(self, core_client):
        current = core_client.get("/api/v1/admin/settings", headers=ADMIN).json()
        r = core_client.patch("/api/v1/admin/settings", json=current, headers=ADMIN)
        assert r.status_code == 200


class TestPartnerApi:
    def test_no_key_rejected(self, partner_client):
        assert partner_client.get("/v1/fact-checks/fc-2026-0142").status_code == 401

    def test_submit_check(self, partner_client):
        r = partner_client.post("/v1/checks", json={"type": "text", "content": "x" * 30}, headers=PARTNER_KEY)
        assert r.status_code == 202

    def test_check_status(self, partner_client):
        r = partner_client.get("/v1/checks/ZL-7K3P-Q9", headers=PARTNER_KEY)
        assert r.status_code == 200

    @pytest.mark.parametrize("report_id", REPORT_IDS)
    def test_get_fact_check(self, partner_client, report_id):
        r = partner_client.get(f"/v1/fact-checks/{report_id}", headers=PARTNER_KEY)
        assert r.status_code == 200, r.text

    def test_search(self, partner_client):
        r = partner_client.get("/v1/fact-checks", params={"q": "internet"}, headers=PARTNER_KEY)
        assert r.status_code == 200, r.text

    def test_rate_limit_headers_present(self, partner_client):
        r = partner_client.get("/v1/fact-checks/fc-2026-0142", headers=PARTNER_KEY)
        assert "X-RateLimit-Limit" in r.headers
        assert "X-RateLimit-Remaining" in r.headers
        assert "X-RateLimit-Reset" in r.headers


def test_health_endpoints_not_in_contract_but_still_ok():
    # /healthz and /readyz are infra endpoints, deliberately not part of the OpenAPI contract.
    # /readyz's dependency checks are tested in tests/db/test_readyz.py.
    assert TestClient(_app).get("/healthz").status_code == 200
