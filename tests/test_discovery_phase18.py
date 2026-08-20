"""Phase 18 — discovery overhaul tests: pagination, role/location gates,
failure isolation, stage counters, fetcher backoff/cooldown, multi-source
dedup/linking, publishable web filtering."""
import json
import io
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from src import db
from src import sources as registry
from src.discovery import ats, fetcher, internship_scout
from src.webapp import create_app

FIXTURES = Path(__file__).parent / "fixtures"


def _source_config(url, method="ats_greenhouse", **extra):
    base = {
        "name": "Test Source", "organization": "Test Org",
        "type": "official_company", "category": "internship",
        "url": url, "method": method, "trust_score": 100, "enabled": True,
    }
    base.update(extra)
    return base


def _sync_sources(tmp_path, sources):
    file = tmp_path / "sources.json"
    file.write_text(json.dumps({"sources": sources}))
    registry.sync_sources(sources)
    return file


def _jobs_payload(n, start=0, total=None):
    return {"jobs": [
        {
            "id_icims": str(i + start), "title": f"Software Engineer Intern {i + start}",
            "locations": [{"name": "Bengaluru, India"}], "posted_date": "2026-08-01",
            "description_short": "internship role", "normalized_location": "Bengaluru",
            "url_next_step": f"https://www.amazon.jobs/en/jobs/{i + start}",
        }
        for i in range(n)
    ], "total_jobs": total if total is not None else n}


class TestPagination:
    def test_offset_pagination_fetches_all_pages(self, monkeypatch, tmp_db):
        calls = []
        real = ats._fetch_json

        def fake_fetch_json(url, max_bytes=None, source=None):
            calls.append(url)
            page = 0
            if "offset=100" in url:
                page = 1
            if page == 0:
                return _jobs_payload(100, start=0, total=197), 200
            return _jobs_payload(97, start=100, total=197), 200

        monkeypatch.setattr(ats, "_fetch_json", fake_fetch_json)
        source = _source_config("https://www.amazon.jobs/en/search.json?base_query=intern")
        source.update(method="ats_json", max_pages=10, result_limit=100)
        entries_list = ats.fetch_ats(source, "ats_json")
        assert len(entries_list) == 197
        assert len([c for c in calls if "offset=0" in c]) == 1
        assert len([c for c in calls if "offset=100" in c]) == 1
        assert not any("offset=200" in c for c in calls)

    def test_pagination_stops_when_no_more_jobs(self, monkeypatch, tmp_db):
        def fake_fetch_json(url, max_bytes=None, source=None):
            if "offset=1" in url:
                return {"jobs": [], "total_jobs": 0}, 200
            return _jobs_payload(3, start=0, total=3), 200

        monkeypatch.setattr(ats, "_fetch_json", fake_fetch_json)
        source = _source_config("https://www.amazon.jobs/en/search.json?base_query=intern",
                                method="ats_json", max_pages=10, result_limit=100)
        entries_list = ats.fetch_ats(source, "ats_json")
        assert len(entries_list) == 3

    def test_pagination_respects_max_pages(self, monkeypatch, tmp_db):
        calls = []

        def fake_fetch_json(url, max_bytes=None, source=None):
            calls.append(url)
            return _jobs_payload(100, start=len(calls) * 100, total=9999), 200

        monkeypatch.setattr(ats, "_fetch_json", fake_fetch_json)
        source = _source_config("https://www.amazon.jobs/en/search.json?base_query=intern",
                                method="ats_json", max_pages=2, result_limit=100)
        entries_list = ats.fetch_ats(source, "ats_json")
        assert len(entries_list) == 200
        assert len(calls) == 2


class TestRoleGate:
    def test_word_boundary_intern_does_not_match_international(self, tmp_db, tmp_path):
        gh_uri = (FIXTURES / "sample_greenhouse.json").as_uri()
        _sync_sources(tmp_path, [_source_config(gh_uri)])
        internship_scout.scout_source(registry.list_enabled_sources("internship")[0])
        titles = [o["title"] for o in db.list_opportunities()]
        assert titles == ["Software Engineering Intern, Security (Summer 2026)"]
        assert "International Account Manager" not in titles

    def test_custom_role_patterns_override_defaults(self, tmp_db, tmp_path):
        gh_uri = (FIXTURES / "sample_greenhouse.json").as_uri()
        _sync_sources(tmp_path, [_source_config(gh_uri, role_patterns=["account manager"],
                                                location_filter="any")])
        internship_scout.scout_source(registry.list_enabled_sources("internship")[0])
        titles = [o["title"] for o in db.list_opportunities()]
        assert titles == ["International Account Manager"]


class TestLocationFilter:
    def _gh_fixture(self, tmp_path, location, remote=False, title="Software Engineer Intern"):
        payload = {"jobs": [{
            "id": 1, "title": title, "location": {"name": location},
            "remote": remote, "updated_at": "2026-08-01",
            "content": "Apply now", "absolute_url": "https://example.org/job/1",
        }]}
        file = tmp_path / "one_job.json"
        file.write_text(json.dumps(payload))
        return file.as_uri()

    def test_india_remote_filter_drops_foreign_onsite(self, tmp_db, tmp_path):
        uri = self._gh_fixture(tmp_path, "San Francisco, CA")
        _sync_sources(tmp_path, [_source_config(uri, location_filter="india_remote")])
        internship_scout.scout_source(registry.list_enabled_sources("internship")[0])
        assert db.list_opportunities() == []

    def test_any_filter_stores_foreign_onsite_as_unclear(self, tmp_db, tmp_path):
        uri = self._gh_fixture(tmp_path, "San Francisco, CA")
        _sync_sources(tmp_path, [_source_config(uri, location_filter="any")])
        internship_scout.scout_source(registry.list_enabled_sources("internship")[0])
        rows = db.list_opportunities()
        assert len(rows) == 1
        assert rows[0]["eligibility_status"] == "unclear"

    def test_india_remote_keeps_india_roles(self, tmp_db, tmp_path):
        uri = self._gh_fixture(tmp_path, "Bengaluru, India")
        _sync_sources(tmp_path, [_source_config(uri, location_filter="india_remote")])
        internship_scout.scout_source(registry.list_enabled_sources("internship")[0])
        rows = db.list_opportunities()
        assert len(rows) == 1
        assert rows[0]["eligibility_status"] in ("eligible", "likely_eligible")


class TestFailureIsolation:
    def test_failed_source_does_not_stop_pipeline(self, tmp_db, tmp_path):
        gh_uri = (FIXTURES / "sample_greenhouse.json").as_uri()
        sources = [
            _source_config("https://boards-api.greenhouse.io/v1/boards/does-not-exist-xyz/jobs"),
            _source_config(gh_uri),
        ]
        _sync_sources(tmp_path, sources)
        total = 0
        for source in registry.list_enabled_sources("internship"):
            _, matched = internship_scout.scout_source(source)
            total += matched
        assert total == 1
        rows = db.list_recent_discovery_runs()
        failed = [r for r in rows if r["error"]]
        ok = [r for r in rows if not r["error"]]
        assert len(failed) == 1
        assert len(ok) == 1
        assert "404" in failed[0]["error"]

    def test_failed_source_increments_consecutive_failures(self, tmp_db, tmp_path):
        sources = [
            _source_config("https://boards-api.greenhouse.io/v1/boards/does-not-exist-xyz/jobs"),
        ]
        _sync_sources(tmp_path, sources)
        source = registry.list_enabled_sources("internship")[0]
        internship_scout.scout_source(source)
        internship_scout.scout_source(source)
        conn = db.get_connection()
        row = conn.execute("SELECT consecutive_failures FROM sources WHERE id = ?", (source["id"],)).fetchone()
        conn.close()
        assert row["consecutive_failures"] >= 2


class TestStageCounters:
    def test_discovery_run_records_stage_counts(self, tmp_db, tmp_path):
        gh_uri = (FIXTURES / "sample_greenhouse.json").as_uri()
        _sync_sources(tmp_path, [_source_config(gh_uri)])
        internship_scout.scout_source(registry.list_enabled_sources("internship")[0])
        rows = db.list_recent_discovery_runs()
        assert len(rows) == 1
        run = rows[0]
        assert run["scout"] == "internship_scout"
        assert run["raw_items"] == 3
        assert run["role_gate"] == 1
        assert run["location_gate"] == 1
        assert run["pattern_gate"] == 1
        assert run["extracted"] == 1
        assert run["stored_new"] == 1
        assert run["published"] == 1
        assert run["error"] is None

    def test_filtering_decisions_recorded(self, tmp_db, tmp_path):
        gh_uri = (FIXTURES / "sample_greenhouse.json").as_uri()
        _sync_sources(tmp_path, [_source_config(gh_uri)])
        internship_scout.scout_source(registry.list_enabled_sources("internship")[0])
        conn = db.get_connection()
        rows = conn.execute("SELECT * FROM filtering_decisions").fetchall()
        conn.close()
        assert len(rows) == 2
        assert {r["stage"] for r in rows} == {"role"}
        assert any("International Account Manager" in r["title"] for r in rows)


class TestFetcherBackoff:
    class _FakeResponse:
        status = 200

        def __init__(self, data=b"{}"):
            self._data = data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size=-1):
            return self._data

        def geturl(self):
            return "https://example.org/jobs"

    def _response(self, data=b"{}"):
        return self._FakeResponse(data)

    def _http_error(self, code, msg="boom"):
        return urllib.error.HTTPError("https://example.org/", code, msg, {}, None)

    def test_retries_5xx_then_succeeds(self, monkeypatch, tmp_db):
        monkeypatch.setattr(fetcher.time, "sleep", lambda s: None)
        calls = {"n": 0}

        def fake_urlopen(request, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise self._http_error(503)
            return self._response()

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        data, final_url, status = fetcher.fetch_bytes("https://example.org/jobs")
        assert calls["n"] == 2
        assert status == 200

    def test_404_fails_fast_without_retry(self, monkeypatch, tmp_db):
        calls = {"n": 0}

        def fake_urlopen(request, timeout=None):
            calls["n"] += 1
            raise self._http_error(404, "Not Found")

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(fetcher.FetchError) as exc:
            fetcher.fetch_bytes("https://example.org/missing")
        assert exc.value.code == 404
        assert calls["n"] == 1

    def test_429_retried_with_long_backoff_then_succeeds(self, monkeypatch, tmp_db):
        monkeypatch.setattr(fetcher.time, "sleep", lambda s: None)
        calls = {"n": 0}

        def fake_urlopen(request, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise self._http_error(429, "Too Many Requests")
            return self._response()

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        data, final_url, status = fetcher.fetch_bytes("https://example.org/jobs")
        assert calls["n"] == 2

    def test_source_cooldown_blocks_fetch(self, tmp_db, tmp_path):
        _sync_sources(tmp_path, [
            _source_config("https://boards-api.greenhouse.io/v1/boards/example/jobs"),
        ])
        source = registry.list_enabled_sources("internship")[0]
        registry.mark_failure(source["id"], "rate limited", cooldown_seconds=300)
        assert db.source_cooldown_remaining(source["id"]) > 0
        with pytest.raises(fetcher.FetchError) as exc:
            fetcher.fetch("https://example.org/jobs", source=source)
        assert exc.value.code == 429


class TestMultiSource:
    def test_same_job_from_two_sources_stored_once(self, tmp_db, tmp_path):
        payload_a = {"jobs": [{
            "id": 7, "title": "ML Research Internship", "location": {"name": "Remote"},
            "remote": True, "updated_at": "2026-08-01", "content": "Apply now",
            "absolute_url": "https://example.org/jobs/7",
        }]}
        payload_b = {"jobs": [{
            "id": 7, "title": "ML Research Internship", "location": {"name": "Remote"},
            "remote": True, "updated_at": "2026-08-01", "content": "Apply now",
            "absolute_url": "https://example.org/jobs/7-mirror",
        }]}
        one = tmp_path / "one.json"
        two = tmp_path / "two.json"
        one.write_text(json.dumps(payload_a))
        two.write_text(json.dumps(payload_b))
        sources = [_source_config(one.as_uri()), _source_config(two.as_uri())]
        _sync_sources(tmp_path, sources)
        for source in registry.list_enabled_sources("internship"):
            internship_scout.scout_source(source)
        opportunities = db.list_opportunities()
        assert len(opportunities) == 1
        conn = db.get_connection()
        canonical = conn.execute(
            "SELECT id FROM opportunities WHERE duplicate_of IS NULL"
        ).fetchone()
        links = conn.execute(
            "SELECT COUNT(*) AS n FROM opportunity_sources WHERE opportunity_id = ?",
            (canonical["id"],),
        ).fetchone()
        conn.close()
        assert links["n"] == 2

    def test_run_records_duplicate_count_on_second_source(self, tmp_db, tmp_path):
        payload_a = {"jobs": [{
            "id": 7, "title": "ML Research Internship", "location": {"name": "Remote"},
            "remote": True, "updated_at": "2026-08-01", "content": "Apply now",
            "absolute_url": "https://example.org/jobs/7",
        }]}
        payload_b = {"jobs": [{
            "id": 7, "title": "ML Research Internship", "location": {"name": "Remote"},
            "remote": True, "updated_at": "2026-08-01", "content": "Apply now",
            "absolute_url": "https://example.org/jobs/7-mirror",
        }]}
        one = tmp_path / "one.json"
        two = tmp_path / "two.json"
        one.write_text(json.dumps(payload_a))
        two.write_text(json.dumps(payload_b))
        _sync_sources(tmp_path, [_source_config(one.as_uri()), _source_config(two.as_uri())])
        for source in registry.list_enabled_sources("internship"):
            internship_scout.scout_source(source)
        rows = db.list_recent_discovery_runs()
        assert rows[0]["stored_new"] == 0
        assert rows[0]["duplicates"] == 1


class TestWebPublishable:
    @pytest.fixture()
    def client(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "opp.db"))
        monkeypatch.setenv("RUN_TOKEN", "test-token")
        monkeypatch.setenv("SESSION_SECRET", "test-secret")
        application = create_app()
        application.config["TESTING"] = True
        for title, status in (
            ("Eligible Intern", "eligible"),
            ("Likely Intern", "likely_eligible"),
            ("Unclear Intern", "unclear"),
            ("Rejected Intern", "not_eligible"),
        ):
            db.upsert_opportunity({
                "title": title, "organization": "Org", "type": "internship",
                "location": "Bengaluru, India", "eligibility_status": status,
            })
        return application.test_client()

    def test_list_defaults_to_publishable(self, client):
        html = client.get("/internships").get_data(as_text=True)
        assert "Eligible Intern" in html
        assert "Likely Intern" in html
        assert "Unclear Intern" not in html
        assert "Rejected Intern" not in html

    def test_review_queue_shows_unclear(self, client):
        html = client.get("/internships?status=unclear").get_data(as_text=True)
        assert "Unclear Intern" in html
        assert "Eligible Intern" not in html
        assert "Review queue" in html

    def test_review_route_shows_only_unclear(self, client):
        html = client.get("/review").get_data(as_text=True)
        assert "Unclear Intern" in html
        assert "Eligible Intern" not in html

    def test_top_excludes_unclear_and_not_eligible(self, client):
        html = client.get("/top").get_data(as_text=True)
        assert "Eligible Intern" in html
        assert "Unclear Intern" not in html
        assert "Rejected Intern" not in html

    def test_detail_of_unclear_still_visible(self, client):
        rows = db.list_opportunities()
        unclear = next(o for o in rows if o["eligibility_status"] == "unclear")
        html = client.get(f"/o/{unclear['id']}").get_data(as_text=True)
        assert "Unclear Intern" in html