"""Admin dashboard + JSON API tests."""
import secrets
from datetime import datetime, timedelta, timezone

import pytest

from src import db, schema
from src.webapp import auth, helpers


def _login(client, user_id):
    token = secrets.token_urlsafe(32)
    db.create_session(
        user_id, token,
        (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    )
    client.set_cookie(auth.SESSION_COOKIE, token)


class TestAdminAuth:
    def test_admin_requires_login(self, client):
        resp = client.get("/admin")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_admin_requires_role(self, client, app):
        # A normal (non-admin-role) user is redirected even with a session.
        with app.app_context():
            uid = db.create_user("student1", password_hash="x", profile={})
        _login(client, uid)
        resp = client.get("/admin")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_admin_works_for_admin(self, client, app, monkeypatch):
        monkeypatch.setenv("ADMIN_USERNAME", "root")
        with app.app_context():
            uid = db.create_user("root", password_hash="x", profile={})
            db.bootstrap_admin("root")
        _login(client, uid)
        resp = client.get("/admin")
        assert resp.status_code == 200
        assert b"Admin" in resp.data


class TestAdminActions:
    def test_toggle_source(self, app, client, monkeypatch):
        monkeypatch.setenv("ADMIN_USERNAME", "root")
        with app.app_context():
            uid = db.create_user("root", password_hash="x", profile={})
            db.bootstrap_admin("root")
            from src import sources as registry
            registry.sync_sources()
            sid = db.get_connection().execute(
                "SELECT id FROM sources LIMIT 1"
            ).fetchone()["id"]
        _login(client, uid)
        resp = client.post(
            f"/admin/sources/{sid}/toggle",
            data={"enabled": "0"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        row = db.get_connection().execute(
            "SELECT enabled FROM sources WHERE id = ?", (sid,)
        ).fetchone()
        assert row["enabled"] == 0

    def test_run_pipeline(self, app, client, monkeypatch):
        monkeypatch.setenv("ADMIN_USERNAME", "root")
        import src.worker as worker
        monkeypatch.setattr(
            "src.discovery.fellowship_scout.run", lambda **k: 0
        )
        monkeypatch.setattr(
            "src.discovery.internship_scout.run", lambda **k: 0
        )
        monkeypatch.setattr(
            "src.discovery.hackathon_scout.run", lambda **k: 0
        )
        monkeypatch.setattr("src.notifications.notifier.run", lambda: 0)
        monkeypatch.setattr("src.ai.assess_new", lambda limit=5: 0)
        monkeypatch.setattr("src.verification.verify_due", lambda limit=20: {})
        monkeypatch.setattr("src.discovery.enrichment.run_enrichment", lambda limit=15: {"candidates": 0, "filled": 0, "confirmed": 0, "conflicts": 0, "unreadable": 0, "no_change": 0})
        monkeypatch.setattr(
            "src.maintenance.run_maintenance",
            lambda: {"expired": 0, "pruned_logs": 0, "pruned_errors": 0,
                     "pruned_notifications": 0},
        )
        with app.app_context():
            uid = db.create_user("root", password_hash="x", profile={})
            db.bootstrap_admin("root")
        _login(client, uid)
        resp = client.post("/admin/run")
        assert resp.status_code == 200
        assert b"Run complete" in resp.data


class TestApi:
    def _client(self, tmp_db):
        import src.api
        from fastapi.testclient import TestClient
        return TestClient(src.api.app)

    def test_health(self, tmp_db):
        assert self._client(tmp_db).get("/health").json()["status"] == "ok"

    def test_opportunities_empty(self, tmp_db):
        r = self._client(tmp_db).get("/opportunities")
        assert r.status_code == 200
        assert r.json()["total"] == 0

    def test_opportunities_with_data(self, tmp_db):
        db.upsert_opportunity({
            "title": "Software Engineer Intern", "organization": "Stripe",
            "type": "internship", "location": "Bengaluru", "country": "India",
            "deadline": "2099-01-01", "eligibility_status": "eligible",
            "application_url": "https://stripe.example/intern",
        })
        r = self._client(tmp_db).get("/opportunities")
        body = r.json()
        assert body["total"] == 1
        item = body["items"][0]
        assert item["title"] == "Software Engineer Intern"
        assert item["deadline_status"] == "Open"
        assert item["trust_score"] is not None
        assert item["trust_label"] in (
            "Highly Verified", "Verified", "Needs Verification", "Low Confidence"
        )

    def test_opportunity_detail_404(self, tmp_db):
        assert self._client(tmp_db).get("/opportunities/999").status_code == 404

    def test_search(self, tmp_db):
        db.upsert_opportunity({
            "title": "Fulbright Fellowship", "organization": "Fulbright",
            "type": "fellowship", "application_url": "https://f.example",
        })
        r = self._client(tmp_db).post(
            "/opportunities/search", json={"query": "fulbright"}
        )
        body = r.json()
        assert body["total"] == 1
        assert body["items"][0]["type"] == "fellowship"

    def test_types(self, tmp_db):
        types = self._client(tmp_db).get("/types").json()["types"]
        assert "hackathon" in types
        assert "scholarship" in types

    def test_report_endpoint(self, tmp_db):
        opp_id = db.upsert_opportunity({
            "title": "T", "organization": "O", "type": "internship",
            "application_url": "https://x.example/a",
        })
        c = self._client(tmp_db)
        r = c.post(f"/report/{opp_id}", params={"reason": "Wrong deadline"})
        assert r.status_code == 200
        assert len(db.list_reports()) == 1

    def test_crawl_needs_token(self, tmp_db):
        c = self._client(tmp_db)
        assert c.post("/crawl").status_code == 403