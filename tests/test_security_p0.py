"""P0 security regression tests: RBAC, session hashing, CSRF, profile privacy."""
import hashlib
import hmac as hmac_mod
import json

import pytest

from src import db
from src.webapp import auth, views


# --- RBAC (0.1) ---

def test_register_reserved_username_rejected(client):
    resp = client.post(
        "/register",
        data={"username": "admin", "password": "hunter22pw", "confirm": "hunter22pw"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "reserved" in resp.get_data(as_text=True).lower()
    assert db.get_user_by_username("admin") is None


def test_new_users_get_user_role(tmp_db):
    uid = db.create_user("alice", "x")
    assert db.get_user_by_id(uid)["role"] == "user"


def test_admin_gate_requires_role_not_name(app, client):
    # A user literally named "admin" but without the role must NOT get access.
    uid = db.create_user("admin", auth.hash_password("hunter22pw"))
    client.post("/login", data={"username": "admin", "password": "hunter22pw"})
    resp = client.get("/admin", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
    # and the role is still 'user'
    assert db.get_user_by_id(uid)["role"] == "user"


def test_bootstrap_admin_grants_role(tmp_db):
    uid = db.create_user("owner", "x")
    assert db.bootstrap_admin("owner") == uid
    assert db.get_user_by_id(uid)["role"] == "admin"
    # idempotent
    assert db.bootstrap_admin("owner") == uid


def test_bootstrap_admin_missing_user_is_noop(tmp_db):
    assert db.bootstrap_admin("") is None
    assert db.bootstrap_admin("nobody-here") is None


def test_set_user_role_validates(tmp_db):
    uid = db.create_user("bob", "x")
    with pytest.raises(ValueError):
        db.set_user_role(uid, "superadmin")


def test_admin_with_role_can_access(app, client, monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "realadmin")
    from src.webapp import create_app  # re-import not needed; call bootstrap directly
    db.create_user("realadmin", auth.hash_password("hunter22pw"))
    db.bootstrap_admin("realadmin")
    client.post("/login", data={"username": "realadmin", "password": "hunter22pw"})
    resp = client.get("/admin")
    assert resp.status_code == 200


# --- Session hashing at rest (0.4) ---

def _all_session_tokens():
    conn = db.get_connection()
    try:
        return [r["token"] for r in conn.execute("SELECT token FROM sessions").fetchall()]
    finally:
        conn.close()


def test_session_stored_hashed_not_plaintext(tmp_db):
    uid = db.create_user("carol", "x")
    token = auth.start_session(uid)
    assert token not in _all_session_tokens()
    assert db.get_session(token) is not None
    assert db.get_session(token)["user_id"] == uid


def test_legacy_plaintext_session_upgraded(tmp_db):
    uid = db.create_user("dave", "x")
    raw = "legacy-raw-token-abcdef0123456789"
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO sessions (user_id, token, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)", (uid, raw, db.now_iso(), "2099-01-01T00:00:00+00:00"),
        )
        conn.commit()
    finally:
        conn.close()
    # Lookup by raw token works once, then the row is upgraded to hashed.
    assert db.get_session(raw)["user_id"] == uid
    assert raw not in _all_session_tokens()
    # A leaked DB value must not work as a credential.
    stored = _all_session_tokens()[0]
    assert db.get_session(stored) is None
    # The upgraded row still authenticates with its original raw token.
    assert db.get_session(raw)["user_id"] == uid


def test_logout_deletes_hashed_session(tmp_db, app, client):
    client.post("/register", data={"username": "erin", "password": "longenough1",
                                   "confirm": "longenough1"})
    cookie = client.get_cookie(auth.SESSION_COOKIE)
    assert cookie and db.get_session(cookie.value) is not None
    client.post("/logout")
    assert db.get_session(cookie.value) is None


# --- FastAPI internal-endpoint auth (0.5) ---

def _api_client(tmp_db):
    import src.api
    from fastapi.testclient import TestClient
    return TestClient(src.api.app)


def test_api_internal_endpoints_need_token(tmp_db, monkeypatch):
    monkeypatch.setenv("RUN_TOKEN", "secret-token")
    c = _api_client(tmp_db)
    for path in ("/crawl/jobs", "/stats", "/api/agents", "/api/agent-tasks",
                 "/api/agent-events", "/api/pipeline/status"):
        assert c.get(path).status_code == 401, path
    assert c.post("/api/agents/extraction_agent/run").status_code == 401


def test_api_internal_endpoints_accept_valid_token(tmp_db, monkeypatch):
    monkeypatch.setenv("RUN_TOKEN", "secret-token")
    c = _api_client(tmp_db)
    headers = {"X-Run-Token": "secret-token"}
    assert c.get("/crawl/jobs", headers=headers).status_code == 200
    assert c.get("/stats", headers=headers).status_code == 200


def test_api_public_reads_stay_public(tmp_db):
    c = _api_client(tmp_db)
    assert c.get("/opportunities").status_code == 200
    assert c.get("/types").status_code == 200
    assert c.get("/sources").status_code == 200


def test_api_report_rate_limited(tmp_db):
    opp_id = db.upsert_opportunity({
        "title": "T", "organization": "O", "type": "internship",
        "application_url": "https://x.example/a",
    })
    c = _api_client(tmp_db)
    statuses = [c.post(f"/report/{opp_id}", params={"reason": f"r{i}"}).status_code
                for i in range(8)]
    assert statuses[:5] == [200] * 5
    assert 429 in statuses[5:]


def test_api_report_returns_report_id(tmp_db):
    opp_id = db.upsert_opportunity({
        "title": "T2", "organization": "O2", "type": "internship",
        "application_url": "https://x.example/b",
    })
    r = _api_client(tmp_db).post(f"/report/{opp_id}", params={"reason": "bad link"})
    body = r.json()
    assert body["ok"] is True
    # The returned id must identify a real reports row (not echo the opp id).
    stored = db.list_reports()[0]
    assert stored["id"] == body["report_id"]
    assert stored["opportunity_id"] == opp_id


# --- CSRF (0.3) ---

def test_authenticated_post_without_csrf_rejected(app, client):
    client.post("/register", data={"username": "frank", "password": "longenough1",
                                   "confirm": "longenough1"})
    # Raw client: bypass the CSRF-injecting wrapper on purpose.
    raw = app.test_client()
    raw.set_cookie(auth.SESSION_COOKIE, client.get_cookie(auth.SESSION_COOKIE).value)
    resp = raw.post("/notifications")
    assert resp.status_code == 400


def test_authenticated_post_with_wrong_csrf_rejected(app, client):
    client.post("/register", data={"username": "gina", "password": "longenough1",
                                   "confirm": "longenough1"})
    raw = app.test_client()
    raw.set_cookie(auth.SESSION_COOKIE, client.get_cookie(auth.SESSION_COOKIE).value)
    resp = raw.post("/notifications", headers={"X-CSRF-Token": "forged"})
    assert resp.status_code == 400


def test_authenticated_post_with_valid_csrf_header_ok(client):
    client.post("/register", data={"username": "hank", "password": "longenough1",
                                   "confirm": "longenough1"})
    # The conftest wrapper injects the header automatically.
    assert client.post("/notifications").status_code in (200, 302)


def test_anonymous_double_submit_cookie_enforced(app, client):
    # First GET sets the anon pairing cookie.
    client.get("/login")
    raw = app.test_client()
    cookie = client.get_cookie(views.ANON_CSRF_COOKIE)
    if cookie and cookie.value:
        raw.set_cookie(views.ANON_CSRF_COOKIE, cookie.value)
        # Cookie present but no token -> rejected.
        resp = raw.post("/login", data={"username": "x", "password": "y"})
        assert resp.status_code == 400
        # Matching token -> accepted (bad creds, but CSRF passed).
        from src.webapp.views import csrf_token_for
        resp = raw.post(
            "/login", data={"username": "x", "password": "y"},
            headers={"X-CSRF-Token": csrf_token_for("anon:" + cookie.value)},
        )
        assert resp.status_code == 200


def test_machine_token_exempt_from_csrf(client, monkeypatch):
    import os as _os
    # /run with X-Run-Token works even without cookies/tokens; stub the pipeline.
    from src import worker as _worker
    monkeypatch.setattr(_worker, "run_pipeline", lambda: {"ok": True})
    resp = client.post("/run", headers={"X-Run-Token": _os.environ.get("RUN_TOKEN", "")})
    assert resp.status_code == 200


def _all_session_tokens():
    conn = db.get_connection()
    try:
        return [r["token"] for r in conn.execute("SELECT token FROM sessions").fetchall()]
    finally:
        conn.close()


# --- Profile privacy in LLM prompts (0.2) ---

def _raw_user_row():
    uid = db.create_user("privacy", "x", email="p@example.com")
    db.update_user_fields(uid, {
        "degree": "B.Tech", "branch": "CSE", "current_year": 2,
        "skills": ["python"], "api_token_hash": "tok-hash",
    })
    conn = db.get_connection()
    try:
        conn.execute(
            "UPDATE users SET password_hash = 'scrypt$secret', api_token_hash = 'tok-hash' "
            "WHERE id = ?", (uid,))
        conn.commit()
    finally:
        conn.close()
    return db.get_user_by_id(uid)


def test_safe_profile_strips_secrets(tmp_db):
    from src import ai
    user = _raw_user_row()
    safe = ai.safe_profile(user)
    blob = json.dumps(safe)
    assert "scrypt" not in blob
    assert "tok-hash" not in blob
    assert "password_hash" not in safe
    assert "api_token_hash" not in safe
    assert "email" not in safe
    assert safe.get("degree") == "B.Tech"
    assert safe.get("skills") == ["python"]


def test_rudra_send_prompt_contains_no_hash(tmp_db, client, monkeypatch):
    import src.ai as ai_mod
    captured = {}

    def fake_chat_ask(messages, system=None, profile=None):
        captured["messages"] = messages
        return "ok", "test"

    monkeypatch.setattr(ai_mod, "chat_ask", fake_chat_ask)
    user = _raw_user_row()
    # log in as that user via session cookie
    token = auth.start_session(user["id"])
    client.set_cookie(auth.SESSION_COOKIE, token)
    client.post("/rudra/send", data={"message": "hello"})
    blob = json.dumps(captured["messages"])
    assert "scrypt$secret" not in blob
    assert "tok-hash" not in blob
