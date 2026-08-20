"""Phase J: SEO, security, performance."""
from src import db


class TestSeo:
    def test_robots_txt(self, client):
        resp = client.get("/robots.txt")
        assert resp.status_code == 200
        assert b"User-agent: *" in resp.data
        assert b"Sitemap:" in resp.data

    def test_sitemap(self, client, tmp_db):
        db.upsert_opportunity({
            "title": "Sitemap Opp", "organization": "S",
            "type": "internship", "application_url": "https://s.example/a",
            "deadline": "2099-01-01",
        })
        resp = client.get("/sitemap.xml")
        assert resp.status_code == 200
        assert b"<urlset" in resp.data
        assert b"detail" not in resp.data or b"<url><loc>" in resp.data
        assert resp.content_type.startswith("application/xml")

    def test_canonical_and_og(self, client):
        resp = client.get("/")
        assert b'rel="canonical"' in resp.data
        assert b'property="og:title"' in resp.data
        assert b"twitter:card" in resp.data

    def test_og_image_exists(self, client):
        resp = client.get("/static/og.png")
        assert resp.status_code == 200
        assert resp.data[:8] == b"\x89PNG\r\n\x1a\n"

    def test_og_meta_on_detail(self, client, tmp_db):
        opp_id = db.upsert_opportunity({
            "title": "Detail OG Opp", "organization": "DOrg",
            "type": "fellowship", "application_url": "https://d.example/a",
        })
        resp = client.get(f"/o/{opp_id}")
        assert b'property="og:title"' in resp.data
        assert b"Detail OG Opp" in resp.data
        assert b'rel="canonical"' in resp.data


class TestSecurity:
    def test_cross_origin_post_blocked(self, client):
        resp = client.post(
            "/o/1/report", headers={"Origin": "https://evil.example"}
        )
        assert resp.status_code == 403

    def test_same_origin_post_allowed(self, client, tmp_db):
        opp_id = db.upsert_opportunity({
            "title": "T", "organization": "O", "type": "internship",
            "application_url": "https://x.example/a",
        })
        resp = client.post(
            f"/o/{opp_id}/report",
            headers={"Origin": "http://localhost"},
            data={"reason": "Wrong deadline"},
        )
        assert resp.status_code == 302

    def test_login_rate_limited(self, client, app):
        from src.webapp import views
        views._AUTH_ATTEMPTS.clear()
        for _ in range(10):
            client.post("/login", data={"username": "x", "password": "y"})
        resp = client.post("/login", data={"username": "x", "password": "y"})
        assert resp.status_code == 429


class TestPerformance:
    def test_indexes_exist(self, tmp_db):
        conn = db.get_connection()
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        finally:
            conn.close()
        names = {r["name"] for r in rows}
        for expected in (
            "idx_opp_deadline_status", "idx_opp_trust_score",
            "idx_opp_type", "idx_opp_last_seen",
        ):
            assert expected in names

    def test_list_uses_index(self, tmp_db):
        conn = db.get_connection()
        try:
            plan = conn.execute(
                "EXPLAIN QUERY PLAN "
                "SELECT * FROM opportunities WHERE deadline_status = 'Open'"
            ).fetchall()
        finally:
            conn.close()
        assert any(
            "idx_opp_deadline_status" in str(dict(row)) for row in plan
        )