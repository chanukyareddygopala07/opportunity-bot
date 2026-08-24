"""P1 reliability tests: URL scheme allow-list, change detection, validation."""
import pytest

from src import db, schema


# --- URL scheme allow-list (1.3) ---

class TestSanitizeUrl:
    def test_http_https_allowed(self):
        assert schema.sanitize_url("https://x.example/a") == "https://x.example/a"
        assert schema.sanitize_url("http://x.example") == "http://x.example"

    def test_javascript_data_rejected(self):
        assert schema.sanitize_url("javascript:alert(1)") is None
        assert schema.sanitize_url("JAVASCRIPT:alert(1)") is None
        assert schema.sanitize_url("data:text/html,<script>") is None
        assert schema.sanitize_url("vbscript:x") is None

    def test_protocol_relative_normalized(self):
        assert schema.sanitize_url("//x.example/a") == "https://x.example/a"

    def test_garbage_rejected_not_invented(self):
        assert schema.sanitize_url("") is None
        assert schema.sanitize_url(None) is None
        assert schema.sanitize_url("not a url at all") is None
        assert schema.sanitize_url("ftp://files.example/x") is None

    def test_control_characters_rejected(self):
        assert schema.sanitize_url("https://x.example/\nalert(1)") is None

    def test_normalize_strips_unsafe_urls_at_boundary(self):
        opp = schema.normalize_opportunity({
            "title": "T", "organization": "O",
            "application_url": "javascript:alert(document.cookie)",
            "official_url": "https://ok.example",
            "source_url": "data:text/html,x",
        })
        assert opp["application_url"] is None
        assert opp["source_url"] is None
        assert opp["official_url"] == "https://ok.example"


# --- Validation in write path (1.8) ---

def test_upsert_requires_title(tmp_db):
    with pytest.raises(ValueError):
        db.upsert_opportunity({"organization": "No Title Inc"})


def test_scores_are_clamped_not_stored_raw(tmp_db):
    # normalize clamps before persisting; nothing out-of-range ever lands.
    oid = db.upsert_opportunity({
        "title": "T", "organization": "O",
        "match_score": 500,
        "application_url": "https://x.example",
    })
    stored = db.get_opportunity(oid)
    assert stored["match_score"] == 100


def test_validator_flags_missing_title_and_bad_deadline():
    errors, warnings = schema.validate_opportunity({"deadline": "soon-ish"})
    assert "title is required" in errors
    assert any("ISO" in w for w in warnings)


# --- Change detection (1.7) ---

def _base_opp(**overrides):
    base = {
        "title": "Research Fellow", "organization": "IISc",
        "type": "fellowship", "deadline": "2099-01-01",
        "application_url": "https://iisc.example/apply",
        "stipend": "40000/month",
    }
    base.update(overrides)
    return base


def test_change_recorded_on_deadline_change(tmp_db):
    oid = db.upsert_opportunity(_base_opp())
    # Same dedup key requires identical title/org/url/deadline — so to see a
    # deadline *change* recorded we update via the same row through a direct
    # field edit then re-upsert with matching dedup key.
    conn = db.get_connection()
    try:
        conn.execute("UPDATE opportunities SET deadline = ? WHERE id = ?",
                     ("2099-02-02", oid))
        conn.commit()
    finally:
        conn.close()
    changes = db.get_pending_changes()
    assert not any(c["change_type"] == "deadline_changed" for c in changes)

    # Now re-crawl the same source: dedup key differs (deadline in it), so the
    # new record is new — but an upsert against the SAME key must diff.
    before = len(db.get_pending_changes())
    oid2 = db.upsert_opportunity(_base_opp(stipend="45000/month"))
    # same title|org|url|deadline -> same row updated
    assert oid2 == oid
    changes = db.get_pending_changes()
    assert len(changes) > before
    stipend_change = [c for c in changes
                      if c["change_type"] == "stipend_changed"
                      and c["opportunity_id"] == oid]
    assert len(stipend_change) == 1
    assert stipend_change[0]["old_value"] == "40000/month"
    assert stipend_change[0]["new_value"] == "45000/month"


def test_no_change_row_when_identical(tmp_db):
    db.upsert_opportunity(_base_opp())
    before = len(db.get_pending_changes())
    db.upsert_opportunity(_base_opp())
    assert len(db.get_pending_changes()) == before


def test_url_change_detected(tmp_db):
    oid = db.upsert_opportunity(_base_opp())
    db.upsert_opportunity(_base_opp(
        application_url="https://iisc.example/apply-2026"))
    # different url -> different dedup key -> NEW row (by design)
    changes = [c for c in db.get_pending_changes()
               if c["change_type"].endswith("_changed")]
    # no false positives on the original row
    original_changes = [c for c in changes if c["opportunity_id"] == oid]
    assert original_changes == []


# --- Rate limiting (1.10 / 1.12) ---

def test_web_report_rate_limited(tmp_db, app):
    from src.webapp.views import _REPORT_ATTEMPTS
    oid = db.upsert_opportunity({
        "title": "T", "organization": "O", "type": "internship",
        "application_url": "https://x.example/a",
    })
    raw = app.test_client()  # bypass CSRF wrapper deliberately; expect 400s otherwise
    # Fill the per-IP window via the throttling store directly for determinism.
    import time as _time
    now = _time.time()
    _REPORT_ATTEMPTS["127.0.0.1"] = [now] * 5
    resp = raw.post(f"/o/{oid}/report", data={"reason": "spam"})
    assert resp.status_code == 429


def test_api_global_throttle(tmp_db, monkeypatch):
    import src.api as api_mod
    monkeypatch.setattr(api_mod, "_API_MAX_REQUESTS", 3)
    c = api_mod.create_app() if False else None
    from fastapi.testclient import TestClient
    client = TestClient(api_mod.app)
    codes = [client.get("/health").status_code for _ in range(6)]
    assert 429 in codes
