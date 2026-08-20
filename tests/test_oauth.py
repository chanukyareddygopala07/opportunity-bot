"""Phase 17 — OAuth (Google/GitHub) login tests with mocked HTTP."""
import os
import pytest

from src import db
from src.webapp import auth, create_app, oauth


@pytest.fixture()
def app(tmp_path):
    db_path = str(tmp_path / "opp.db")
    os.environ["DATABASE_PATH"] = db_path
    os.environ["SESSION_SECRET"] = "test-secret"
    os.environ["OAUTH_REDIRECT_BASE"] = "http://localhost:8080"
    os.environ["GOOGLE_CLIENT_ID"] = "g-id"
    os.environ["GOOGLE_CLIENT_SECRET"] = "g-secret"
    os.environ["GITHUB_CLIENT_ID"] = "gh-id"
    os.environ["GITHUB_CLIENT_SECRET"] = "gh-secret"
    application = create_app()
    application.config["TESTING"] = True
    yield application
    for key in ("DATABASE_PATH", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
                "GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET", "OAUTH_REDIRECT_BASE"):
        os.environ.pop(key, None)


@pytest.fixture()
def client(app):
    return app.test_client()


def test_auth_urls_include_redirect_and_state(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "g-id")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "gh-id")
    monkeypatch.setenv("OAUTH_REDIRECT_BASE", "http://localhost:8080")
    state = "abc123"
    url = oauth.google_auth_url(state)
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=g-id" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8080%2Fauth%2Fgoogle%2Fcallback" in url
    assert f"state={state}" in url
    url2 = oauth.github_auth_url(state)
    assert url2.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=gh-id" in url2


def test_start_redirects_to_provider(client):
    resp = client.get("/auth/google")
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("https://accounts.google.com")
    assert oauth.STATE_COOKIE in resp.headers["Set-Cookie"]
    resp = client.get("/auth/github")
    assert resp.headers["Location"].startswith("https://github.com/login/oauth/authorize")
    assert client.get("/auth/unknown").status_code == 404


def test_google_callback_creates_user(client, monkeypatch):
    state = oauth.new_state()
    client.set_cookie(oauth.STATE_COOKIE, state)

    def fake_exchange(code):
        return {"provider": "google", "provider_id": "112233",
                "email": "alice@gmail.com", "name": "Alice Chen"}

    monkeypatch.setattr("src.webapp.views.oauth.google_exchange", fake_exchange)
    resp = client.get(f"/auth/google/callback?code=abc&state={state}")
    assert resp.status_code == 302
    user = db.get_user_by_oauth("google", "112233")
    assert user is not None
    assert user["email"] == "alice@gmail.com"
    assert user["username"] == "alice"
    assert user["password_hash"] is None
    cookies = "; ".join(resp.headers.getlist("Set-Cookie"))
    assert f"{auth.SESSION_COOKIE}=" in cookies


def test_oauth_state_mismatch_rejected(client):
    client.set_cookie(oauth.STATE_COOKIE, "expected-state")
    resp = client.get("/auth/google/callback?code=abc&state=wrong")
    assert resp.status_code == 400
    assert db.get_user_by_oauth("google", "1") is None


def test_oauth_callback_missing_code(client):
    client.set_cookie(oauth.STATE_COOKIE, "s")
    resp = client.get("/auth/google/callback?state=s&error=access_denied")
    assert resp.status_code == 400
    assert b"cancelled or denied" in resp.get_data()


def test_github_callback_links_to_existing_email(client, monkeypatch):
    existing = db.create_user("existinguser", auth.hash_password("password123"),
                              email="bob@example.com")
    state = oauth.new_state()
    client.set_cookie(oauth.STATE_COOKIE, state)

    def fake_exchange(code):
        return {"provider": "github", "provider_id": "778899",
                "email": "bob@example.com", "name": "Bob"}

    monkeypatch.setattr("src.webapp.views.oauth.github_exchange", fake_exchange)
    resp = client.get(f"/auth/github/callback?code=abc&state={state}")
    assert resp.status_code == 302
    linked = db.get_user_by_oauth("github", "778899")
    assert linked is not None and linked["id"] == existing
    assert db.get_user_by_username("existinguser")["github_id"] == "778899"


def test_unique_username_collision(app):
    db.create_user("alice", auth.hash_password("password123"))
    assert oauth.unique_username("Alice", "x@y.com") == "alice2"


def test_oauth_failure_shows_error(client, monkeypatch):
    state = oauth.new_state()
    client.set_cookie(oauth.STATE_COOKIE, state)

    def boom(code):
        raise oauth.OAuthError("token exchange failed")

    monkeypatch.setattr("src.webapp.views.oauth.google_exchange", boom)
    resp = client.get(f"/auth/google/callback?code=abc&state={state}")
    assert resp.status_code == 400
    assert b"OAuth failed" in resp.get_data()