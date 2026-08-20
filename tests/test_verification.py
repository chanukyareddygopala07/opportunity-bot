from pathlib import Path

import pytest

from src import db, verification
from src.discovery import fetcher

FIXTURES = Path(__file__).parent / "fixtures"


class TestCheckLink:
    def test_live_file_url(self):
        status, message = verification.check_link((FIXTURES / "sample_feed.xml").as_uri())
        assert status == "live"

    def test_missing_file_is_error(self, tmp_path):
        status, message = verification.check_link((tmp_path / "nope.xml").as_uri())
        assert status == "error"

    def test_http_404_is_dead(self, monkeypatch):
        def fake_fetch(url, **kwargs):
            raise fetcher.FetchError("HTTP Error 404: Not Found", code=404)

        monkeypatch.setattr(verification.fetcher, "fetch_bytes", fake_fetch)
        assert verification.check_link("https://example.org/missing")[0] == "dead"

    def test_http_500_is_dead(self, monkeypatch):
        def fake_fetch(url, **kwargs):
            raise fetcher.FetchError("HTTP Error 500: Boom", code=500)

        monkeypatch.setattr(verification.fetcher, "fetch_bytes", fake_fetch)
        assert verification.check_link("https://example.org/broken")[0] == "dead"

    def test_http_403_is_dead(self, monkeypatch):
        def fake_fetch(url, **kwargs):
            raise fetcher.FetchError("HTTP Error 403: Forbidden", code=403)

        monkeypatch.setattr(verification.fetcher, "fetch_bytes", fake_fetch)
        assert verification.check_link("https://example.org/blocked")[0] == "dead"

    def test_network_error_is_error(self, monkeypatch):
        def fake_fetch(url, **kwargs):
            raise fetcher.FetchError("failed after 1 attempts: timeout")

        monkeypatch.setattr(verification.fetcher, "fetch_bytes", fake_fetch)
        assert verification.check_link("https://example.org/timeout")[0] == "error"


def _insert(trust=100, status="official", url=None):
    return db.upsert_opportunity({
        "title": "Verified Scheme 2026",
        "organization": "Test Org",
        "type": "fellowship",
        "category": "fellowship",
        "application_url": url or (FIXTURES / "sample_feed.xml").as_uri(),
        "organization_trust_score": trust,
        "verification_status": status,
    })


class TestVerifyOpportunity:
    def test_official_live_becomes_verified(self, tmp_db):
        opp_id = _insert(trust=100, status="official")
        status, message = verification.verify_opportunity(opp_id)
        assert status == "verified"
        assert db.get_opportunity(opp_id)["verification_status"] == "verified"
        conn = db.get_connection()
        row = conn.execute("SELECT * FROM verifications WHERE opportunity_id = ?", (opp_id,)).fetchone()
        conn.close()
        assert row["status"] == "verified"
        assert row["link_status"] == "live"

    def test_pending_live_stays_unverified(self, tmp_db):
        opp_id = _insert(trust=50, status="pending")
        status, message = verification.verify_opportunity(opp_id)
        assert status == "unverified"
        assert "not official" in message

    def test_dead_link_is_unverified(self, tmp_db, monkeypatch):
        def fake_fetch(url, **kwargs):
            raise fetcher.FetchError("HTTP Error 404: Not Found", code=404)

        monkeypatch.setattr(verification.fetcher, "fetch_bytes", fake_fetch)
        opp_id = _insert(trust=100, status="official")
        status, message = verification.verify_opportunity(opp_id)
        assert status == "unverified"
        assert "dead" in message

    def test_link_error_keeps_previous_status(self, tmp_db, monkeypatch):
        def fake_fetch(url, **kwargs):
            raise fetcher.FetchError("failed after 1 attempts: timeout")

        monkeypatch.setattr(verification.fetcher, "fetch_bytes", fake_fetch)
        opp_id = _insert(trust=100, status="official")
        status, message = verification.verify_opportunity(opp_id)
        assert status == "official"
        assert db.get_opportunity(opp_id)["verification_status"] == "official"
        conn = db.get_connection()
        row = conn.execute("SELECT * FROM verifications WHERE opportunity_id = ?", (opp_id,)).fetchone()
        conn.close()
        assert row["status"] == "official"
        assert row["link_status"] == "error"

    def test_corroborated_sources_verify_pending(self, tmp_db):
        opp_id = _insert(trust=50, status="pending")
        conn = db.get_connection()
        for name, url in (("Src A", "https://a.example/"), ("Src B", "https://b.example/")):
            source_id = conn.execute(
                "INSERT INTO sources (name, organization, type, category, url, method, trust_score, enabled) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                (name, "Test Org", "official_university", "fellowship", url, "rss", 50),
            ).lastrowid
            conn.execute(
                "INSERT INTO opportunity_sources (opportunity_id, source_id, seen_at) VALUES (?, ?, ?)",
                (opp_id, source_id, db.now_iso()),
            )
        conn.commit()
        conn.close()
        status, message = verification.verify_opportunity(opp_id)
        assert status == "verified"
        assert "corroborated" in message

    def test_no_url_is_unverified(self, tmp_db):
        opp_id = db.upsert_opportunity({
            "title": "No Link Scheme",
            "organization": "Test Org",
            "type": "fellowship",
        })
        status, message = verification.verify_opportunity(opp_id)
        assert status == "unverified"
        assert db.get_opportunity(opp_id)["verification_status"] == "unverified"

    def test_missing_opportunity_returns_none(self, tmp_db):
        assert verification.verify_opportunity(999999) is None


class TestVerifyAll:
    def test_counts_and_limits(self, tmp_db):
        official = _insert(trust=100, status="official")
        pending = _insert(trust=50, status="pending", url=(FIXTURES / "sample_news.html").as_uri())
        counts = verification.verify_all(limit=1)
        assert sum(counts.values()) == 1
        counts = verification.verify_all()
        assert counts == {"verified": 1, "unverified": 1}

    def test_only_pending_skips_verified(self, tmp_db):
        _insert(trust=100, status="official")
        other = _insert(trust=50, status="pending", url=(FIXTURES / "sample_news.html").as_uri())
        verification.verify_all()
        assert db.get_opportunity(other)["verification_status"] == "unverified"