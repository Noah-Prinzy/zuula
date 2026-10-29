"""Admin behaviour end to end, through the contract-validating client (P3 PR 4): the overview
is computed, moderation hides comments and is audited, sources and broadcasts are real,
settings changes are validated, audited and re-score every report (decision 6b), and an
admin can drop a user's ratings (decision 6a)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.adapters import sms
from app.db import models as m
from app.services import brigading
from tests.contract.conftest import ADMIN, EXPERT, PUBLIC


def audit_entries(client, action: str) -> list[dict]:
    return client.get("/api/v1/admin/audit-log", params={"action": action}, headers=ADMIN).json()[
        "data"
    ]


class TestOverview:
    def test_computed_from_the_database(self, core_client):
        body = core_client.get("/api/v1/admin/overview", headers=ADMIN).json()
        kpis = {k["id"]: k for k in body["kpis"]}
        assert set(kpis) == {
            "f1",
            "deepfake",
            "mau",
            "latency",
            "ratings",
            "turnaround",
            "partners",
            "languages",
        }
        assert kpis["languages"]["value"] == 5
        assert kpis["partners"]["value"] >= 1  # the test partner key's owner
        assert len(body["dailyChecks"]) == 14
        reports = core_client.get("/api/v1/fact-checks", params={"perPage": 50}).json()["total"]
        # Every report counts in the verdict mix, suspended ones included.
        assert sum(v["count"] for v in body["verdictMix"]) == reports + 1
        assert {h["label"] for h in body["systemHealth"]} >= {"Database", "Analysis queue"}

    def test_monthly_reports(self, core_client):
        months = core_client.get("/api/v1/admin/reports", headers=ADMIN).json()
        september = next(m for m in months if m["month"] == "2026-09")
        assert september["checks"] == 12  # the sample reports
        assert 0 < september["falseShare"] < 100 and len(september["topCategories"]) <= 3


class TestUsers:
    def test_status_counts_cover_every_account_not_just_the_page(self, core_client):
        def total(status):
            url = f"/api/v1/admin/users?perPage=1&status={status}"
            return core_client.get(url, headers=ADMIN).json()["total"]

        core_client.patch("/api/v1/admin/users/u6", json={"status": "suspended"}, headers=ADMIN)
        page = core_client.get("/api/v1/admin/users?perPage=1&role=admin", headers=ADMIN).json()
        assert len(page["data"]) == 1
        assert page["counts"] == {"pending": total("pending"), "suspended": total("suspended")}
        assert page["counts"]["suspended"] >= 1
        core_client.patch("/api/v1/admin/users/u6", json={"status": "active"}, headers=ADMIN)


class TestModeration:
    def test_dismissing_closes_the_item(self, core_client):
        items = core_client.get("/api/v1/admin/moderation/reports", headers=ADMIN).json()["data"]
        assert [i["reporters"] for i in items] == sorted(
            (i["reporters"] for i in items), reverse=True
        )
        r = core_client.post(
            "/api/v1/admin/moderation/reports/cr1/resolve",
            json={"action": "dismiss"},
            headers=ADMIN,
        )
        assert r.status_code == 200
        left = core_client.get("/api/v1/admin/moderation/reports", headers=ADMIN).json()["data"]
        assert "cr1" not in {i["id"] for i in left}
        again = core_client.post(
            "/api/v1/admin/moderation/reports/cr1/resolve",
            json={"action": "dismiss"},
            headers=ADMIN,
        )
        assert again.status_code == 404

    def test_removing_hides_the_reported_comment_and_is_audited(self, core_client):
        comment = core_client.post(
            "/api/v1/fact-checks/fc-2026-0154/comments",
            json={"vote": "inaccurate", "body": "An insulting comment."},
            headers=PUBLIC,
        ).json()
        core_client.post(
            "/api/v1/fact-checks/fc-2026-0154/report-issue",
            json={"reason": "Offensive comment", "commentId": comment["id"]},
            headers=EXPERT,
        )
        item = next(
            i
            for i in core_client.get("/api/v1/admin/moderation/reports", headers=ADMIN).json()[
                "data"
            ]
            if i["reportId"] == "fc-2026-0154"
        )
        r = core_client.post(
            f"/api/v1/admin/moderation/reports/{item['id']}/resolve",
            json={"action": "remove", "note": "Abusive language"},
            headers=ADMIN,
        )
        assert r.status_code == 200
        comments = core_client.get("/api/v1/fact-checks/fc-2026-0154/comments").json()["data"]
        assert comment["id"] not in {c["id"] for c in comments}
        entry = audit_entries(core_client, "moderation.remove")[0]
        assert (
            entry["target"] == "Comment on fc-2026-0154" and entry["detail"] == "Abusive language"
        )

    def test_a_verdict_itself_cannot_be_removed(self, core_client):
        r = core_client.post(
            "/api/v1/admin/moderation/reports/cr2/resolve", json={"action": "remove"}, headers=ADMIN
        )
        assert r.status_code == 400


class TestSignals:
    def test_brigading_is_detected(self, core_client):
        async def brigade(session):
            now = datetime.now(UTC)
            for i in range(30):
                session.add(
                    m.User(
                        id=f"new-{i}",
                        name=f"New {i}",
                        email=f"new{i}@example.com",
                        created_at=now - timedelta(hours=1),
                    )
                )
            await session.flush()
            session.add_all(
                m.Rating(
                    report_id="fc-2026-0153",
                    user_id=f"new-{i}",
                    vote="inaccurate",
                    rater_role="public",
                    created_at=now,
                    updated_at=now,
                )
                for i in range(30)
            )
            await session.flush()
            return len(await brigading.detect(session))

        assert core_client.run_db(brigade) == 1
        signals = core_client.get("/api/v1/admin/moderation/signals", headers=ADMIN).json()
        signal = next(s for s in signals if s["reportId"] == "fc-2026-0153")
        assert signal["accounts"] == 30 and signal["direction"] == "inaccurate"
        # The same burst isn't reported twice while its signal is open.
        assert core_client.run_db(brigading.detect) == []


class TestSources:
    SOURCE = {
        "name": "KFM",
        "domain": "https://www.kfm.co.ug/",
        "type": "media",
        "languages": ["English"],
        "tier": 2,
    }

    def test_add_is_normalised_and_audited(self, core_client):
        r = core_client.post("/api/v1/admin/sources", json=self.SOURCE, headers=ADMIN)
        assert r.status_code == 201
        assert r.json()["domain"] == "kfm.co.ug" and r.json()["active"] is True
        assert (
            audit_entries(core_client, "source.add")[0]["detail"] == "Media house, English, tier 2"
        )
        dup = core_client.post("/api/v1/admin/sources", json=self.SOURCE, headers=ADMIN)
        assert dup.status_code == 409

    def test_remove_deactivates_and_is_audited(self, core_client):
        assert core_client.delete("/api/v1/admin/sources/s4", headers=ADMIN).status_code == 204
        sources = core_client.get(
            "/api/v1/admin/sources", params={"perPage": 50}, headers=ADMIN
        ).json()["data"]
        assert next(s for s in sources if s["id"] == "s4")["active"] is False
        assert audit_entries(core_client, "source.deactivate")[0]["target"] == "Nile Post"
        assert core_client.delete("/api/v1/admin/sources/nope", headers=ADMIN).status_code == 404


class TestBroadcasts:
    def test_everyone_gets_it_in_app_and_opted_in_phones_by_sms(self, core_client):
        async def amina_wants_sms(session):
            await session.execute(
                update(m.User).where(m.User.id == "u6").values(phone="+256700111222")
            )
            row = await session.get(m.AlertSettings, "u6")
            row.settings = {**row.settings, "channels": {**row.settings["channels"], "sms": True}}

        core_client.run_db(amina_wants_sms)
        r = core_client.post(
            "/api/v1/admin/broadcasts",
            json={
                "title": "Scam alert",
                "message": "Don't share your PIN.",
                "severity": "critical",
                "audience": "Everyone",
                "channels": ["in-app", "sms"],
            },
            headers=ADMIN,
        )
        assert r.status_code == 202
        broadcast = r.json()

        async def active_users(session):
            return len(
                (
                    await session.scalars(
                        select(m.User.id).where(
                            m.User.status != "suspended", m.User.deleted_at.is_(None)
                        )
                    )
                ).all()
            )

        assert broadcast["reach"] == core_client.run_db(active_users)
        note = core_client.get("/api/v1/notifications", headers=PUBLIC).json()["data"][0]
        assert note["kind"] == "broadcast" and note["title"] == "Scam alert"
        assert sms.OUTBOX[-1]["to"] == "+256700111222"
        assert audit_entries(core_client, "broadcast.send")[0]["target"] == broadcast["id"]
        listed = core_client.get("/api/v1/admin/broadcasts", headers=ADMIN).json()
        assert listed[0]["id"] == broadcast["id"]


class TestSettings:
    def _settings(self, client):
        return client.get("/api/v1/admin/settings", headers=ADMIN).json()

    def test_inconsistent_bands_are_rejected(self, core_client):
        s = self._settings(core_client)
        s["thresholds"]["escalatedMax"] = 80  # above the questioned band
        assert core_client.patch("/api/v1/admin/settings", json=s, headers=ADMIN).status_code == 400

    def test_changes_are_audited_and_rescore_every_report(self, core_client):
        # Widen "escalated" to CCS ≤ 55 with > 60 ratings: fc-2026-0158 (53, 69 ratings) and
        # fc-2026-0159 (55, 94) now escalate; their open cases are upgraded (decision 6b).
        s = self._settings(core_client)
        s["thresholds"].update({"escalatedMax": 55, "escalatedRatings": 60, "questionedMin": 56})
        r = core_client.patch("/api/v1/admin/settings", json=s, headers=ADMIN)
        assert r.status_code == 200 and r.json()["thresholds"]["escalatedMax"] == 55

        report = core_client.get("/api/v1/fact-checks/fc-2026-0158").json()
        assert report["community"]["score"]["status"] == "escalated"
        case = core_client.get("/api/v1/review/cases/rc-0416", headers=EXPERT).json()["case"]
        assert case["reason"] == "community-escalation"
        detail = audit_entries(core_client, "settings.update")[0]["detail"]
        assert "Escalated: max score 39 → 55" in detail

    def test_weights_apply_to_new_scores(self, core_client):
        s = self._settings(core_client)
        s["weights"]["expert"] = 10
        core_client.patch("/api/v1/admin/settings", json=s, headers=ADMIN)
        before = core_client.get("/api/v1/fact-checks/fc-2026-0142").json()["community"]["score"]
        after = core_client.post(
            "/api/v1/fact-checks/fc-2026-0142/ratings", json={"vote": "accurate"}, headers=EXPERT
        ).json()
        assert after["weightedAccurate"] == before["weightedAccurate"] + 10


class TestExcludeRatings:
    def test_a_suspended_users_ratings_can_be_dropped_and_restored(self, core_client):
        url = "/api/v1/fact-checks/fc-2026-0161"
        before = core_client.get(url).json()["community"]["score"]["total"]
        r = core_client.patch(
            "/api/v1/admin/users/u6",
            json={"status": "suspended", "excludeRatings": True},
            headers=ADMIN,
        )
        assert r.status_code == 200
        assert core_client.get(url).json()["community"]["score"]["total"] == before - 1
        assert audit_entries(core_client, "ratings.exclude")[0]["detail"].startswith("Dropped")

        core_client.patch(
            "/api/v1/admin/users/u6",
            json={"status": "active", "excludeRatings": False},
            headers=ADMIN,
        )
        assert core_client.get(url).json()["community"]["score"]["total"] == before
