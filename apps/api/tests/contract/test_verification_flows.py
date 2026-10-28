"""Accreditation review end to end (FR-AUTH-02), through the contract-validating client: a
user applies with documents, an admin works the queue, opens the documents through signed,
virus-scanned links, and approves (the role changes, audited, applicant notified in-app and
by email) or rejects with a note (the role stays)."""

from urllib.parse import parse_qs, urlparse

from app.adapters import clamav, email
from app.services import accreditation_documents
from tests.contract.conftest import ADMIN, EXPERT, JOURNALIST, PUBLIC

PDF = b"%PDF-1.7\n" + b"\0" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64


def apply(client, role: str = "journalist", headers=PUBLIC):
    return client.post(
        "/api/v1/me/verification",
        data={"organisation": "Daily Monitor", "pressCardNumber": "UMC-1234", "role": role},
        files=[
            ("documents", ("press-card.pdf", PDF, "application/pdf")),
            ("documents", ("id.png", PNG, "image/png")),
        ],
        headers=headers,
    )


def pending_for(client, name: str) -> dict:
    items = client.get(
        "/api/v1/admin/verifications", params={"status": "pending"}, headers=ADMIN
    ).json()["data"]
    return next(i for i in items if i["applicant"]["name"] == name)


def audit_entries(client, action: str) -> list[dict]:
    return client.get("/api/v1/admin/audit-log", params={"action": action}, headers=ADMIN).json()[
        "data"
    ]


def role_of(client, headers) -> str:
    return client.get("/api/v1/me", headers=headers).json()["role"]


class TestQueue:
    def test_lists_pending_applications_with_their_applicant(self, core_client):
        assert apply(core_client).status_code == 202
        item = pending_for(core_client, "Amina Nakato")
        assert item["requestedRole"] == "journalist"
        assert item["organisation"] == "Daily Monitor"
        assert item["documentCount"] == 2
        assert item["applicant"]["role"] == "public"
        # Grace Nankya's seeded application is pending too.
        r = core_client.get("/api/v1/admin/verifications", headers=ADMIN).json()
        assert r["total"] >= 2 and {i["status"] for i in r["data"]} == {"pending"}

    def test_unknown_status_is_400(self, core_client):
        r = core_client.get("/api/v1/admin/verifications", params={"status": "nope"}, headers=ADMIN)
        assert r.status_code == 400

    def test_detail_has_signed_document_links(self, core_client):
        apply(core_client)
        item = pending_for(core_client, "Amina Nakato")
        detail = core_client.get(f"/api/v1/admin/verifications/{item['id']}", headers=ADMIN)
        assert detail.status_code == 200
        documents = detail.json()["documents"]
        assert [d["index"] for d in documents] == [0, 1]

        pdf = core_client.get(documents[0]["url"])
        assert pdf.status_code == 200
        assert pdf.content == PDF and pdf.headers["content-type"] == "application/pdf"
        png = core_client.get(documents[1]["url"])
        assert png.content == PNG and png.headers["content-type"] == "image/png"

    def test_unknown_application_is_404(self, core_client):
        r = core_client.get("/api/v1/admin/verifications/acc_nope", headers=ADMIN)
        assert r.status_code == 404


class TestDocuments:
    def _url(self, client) -> str:
        apply(client)
        item = pending_for(client, "Amina Nakato")
        detail = client.get(f"/api/v1/admin/verifications/{item['id']}", headers=ADMIN).json()
        return detail["documents"][0]["url"]

    def test_a_tampered_link_is_refused(self, core_client):
        url = self._url(core_client)
        assert core_client.get(url.replace("/documents/0", "/documents/1")).status_code == 403
        assert core_client.get(url[:-4] + "0000").status_code == 403

    def test_an_expired_link_is_refused(self, core_client, monkeypatch):
        url = self._url(core_client)
        monkeypatch.setattr(accreditation_documents.time, "time", lambda: 4_000_000_000)
        assert core_client.get(url).status_code == 403

    def test_a_link_needs_its_signature(self, core_client):
        url = self._url(core_client)
        query = parse_qs(urlparse(url).query)
        signed = urlparse(url).path
        r = core_client.get(signed, params={"expires": query["expires"][0], "sig": "0" * 64})
        assert r.status_code == 403

    def test_an_infected_document_is_never_served(self, core_client, monkeypatch):
        class Infected:
            async def scan(self, data):
                return clamav.ScanResult(clean=False, signature="Eicar-Test-Signature")

        url = self._url(core_client)
        monkeypatch.setattr("app.api.v1.admin.get_clamav_scanner", Infected)
        r = core_client.get(url)
        assert r.status_code == 422 and "Eicar" in r.json()["error"]["message"]

    def test_an_unscannable_document_is_never_served(self, core_client, monkeypatch):
        class Down:
            async def scan(self, data):
                raise clamav.ScanError("clamd is down")

        url = self._url(core_client)
        monkeypatch.setattr("app.api.v1.admin.get_clamav_scanner", Down)
        assert core_client.get(url).status_code == 500


class TestDecisions:
    def test_approving_grants_the_role_audits_and_notifies(self, core_client):
        apply(core_client)
        item = pending_for(core_client, "Amina Nakato")
        r = core_client.post(
            f"/api/v1/admin/verifications/{item['id']}/decision",
            json={"decision": "approve"},
            headers=ADMIN,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "approved" and body["reviewer"] == "Mary Akello"
        assert body["applicant"]["role"] == "journalist"
        assert role_of(core_client, PUBLIC) == "journalist"  # effective on the next request

        entry = audit_entries(core_client, "accreditation.approve")[0]
        assert entry["target"] == "Amina Nakato"
        assert entry["detail"] == "Public User → Verified Journalist (Daily Monitor)"

        status = core_client.get("/api/v1/me/verification", headers=PUBLIC).json()
        assert status["status"] == "approved" and status["role"] == "journalist"
        notes = core_client.get("/api/v1/notifications", headers=PUBLIC).json()["data"]
        assert notes[0]["kind"] == "accreditation" and notes[0]["title"] == "Accreditation approved"
        assert email.OUTBOX[-1]["to"] == "amina@example.com"
        assert email.OUTBOX[-1]["subject"] == "Zuula: Accreditation approved"

    def test_an_expert_application_makes_an_expert(self, core_client):
        assert apply(core_client, role="expert", headers=JOURNALIST).status_code == 202
        item = pending_for(core_client, "Sarah Namutebi")
        assert item["requestedRole"] == "expert"
        core_client.post(
            f"/api/v1/admin/verifications/{item['id']}/decision",
            json={"decision": "approve"},
            headers=ADMIN,
        )
        assert role_of(core_client, JOURNALIST) == "expert"

    def test_rejecting_keeps_the_role_and_tells_the_applicant_why(self, core_client):
        apply(core_client)
        item = pending_for(core_client, "Amina Nakato")
        r = core_client.post(
            f"/api/v1/admin/verifications/{item['id']}/decision",
            json={"decision": "reject", "note": "The press card has expired."},
            headers=ADMIN,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "rejected"
        assert role_of(core_client, PUBLIC) == "public"
        entry = audit_entries(core_client, "accreditation.reject")[0]
        assert entry["detail"] == "Verified Journalist: The press card has expired."
        status = core_client.get("/api/v1/me/verification", headers=PUBLIC).json()
        assert status["status"] == "rejected" and status["note"] == "The press card has expired."
        assert "The press card has expired." in email.OUTBOX[-1]["body"]
        # Rejected, they can apply again.
        assert apply(core_client).status_code == 202

    def test_rejecting_needs_a_note(self, core_client):
        apply(core_client)
        item = pending_for(core_client, "Amina Nakato")
        r = core_client.post(
            f"/api/v1/admin/verifications/{item['id']}/decision",
            json={"decision": "reject"},
            headers=ADMIN,
        )
        assert r.status_code == 400
        assert role_of(core_client, PUBLIC) == "public"

    def test_a_decided_application_cannot_be_decided_again(self, core_client):
        apply(core_client)
        item = pending_for(core_client, "Amina Nakato")
        url = f"/api/v1/admin/verifications/{item['id']}/decision"
        core_client.post(url, json={"decision": "approve"}, headers=ADMIN)
        again = core_client.post(
            url, json={"decision": "reject", "note": "Changed my mind"}, headers=ADMIN
        )
        assert again.status_code == 409
        assert role_of(core_client, PUBLIC) == "journalist"

    def test_a_pending_account_becomes_active(self, core_client):
        item = pending_for(core_client, "Grace Nankya")  # seeded with status "pending"
        r = core_client.post(
            f"/api/v1/admin/verifications/{item['id']}/decision",
            json={"decision": "approve"},
            headers=ADMIN,
        )
        assert r.json()["applicant"]["status"] == "active"


class TestApplying:
    def test_unknown_role_is_400(self, core_client):
        assert apply(core_client, role="admin").status_code == 400

    def test_cannot_apply_for_the_role_you_have(self, core_client):
        assert apply(core_client, headers=JOURNALIST).status_code == 409
        assert apply(core_client, role="expert", headers=EXPERT).status_code == 409


class TestAdminOnly:
    def test_non_admins_get_403(self, core_client):
        apply(core_client)
        item = pending_for(core_client, "Amina Nakato")
        for headers in (PUBLIC, JOURNALIST, EXPERT):
            assert (
                core_client.get("/api/v1/admin/verifications", headers=headers).status_code == 403
            )
            assert (
                core_client.get(
                    f"/api/v1/admin/verifications/{item['id']}", headers=headers
                ).status_code
                == 403
            )
            r = core_client.post(
                f"/api/v1/admin/verifications/{item['id']}/decision",
                json={"decision": "approve"},
                headers=headers,
            )
            assert r.status_code == 403
        assert role_of(core_client, PUBLIC) == "public"

    def test_signed_out_gets_401(self, core_client):
        assert core_client.get("/api/v1/admin/verifications").status_code == 401
