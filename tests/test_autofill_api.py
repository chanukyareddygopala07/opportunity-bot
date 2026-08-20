"""Phase 20 — autofill API tests: token flow + resume payload."""
import json


def _register_and_login(client):
    client.post(
        "/register",
        data={"username": "filluser", "password": "pw123456", "confirm": "pw123456"},
    )
    client.post("/login", data={"username": "filluser", "password": "pw123456"})


def test_token_page_requires_login(client):
    assert client.get("/api/autofill/token").status_code == 302


def test_token_generation(client):
    _register_and_login(client)
    resp = client.post("/api/autofill/token", follow_redirects=True)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Token exists" in body


def test_resume_api_requires_token(client):
    resp = client.get("/api/autofill/resume")
    assert resp.status_code == 401


def test_resume_api_rejects_wrong_token(client):
    resp = client.get(
        "/api/autofill/resume",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert resp.status_code == 401


def test_resume_api_returns_profile(client):
    _register_and_login(client)
    client.post("/api/autofill/token")
    from src import db
    from src.webapp import auth
    user = db.get_user_by_username("filluser")
    token = "test-token-abc123"
    db.set_api_token_hash(user["id"], auth.hash_password(token))
    resp = client.get(
        "/api/autofill/resume",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["name"] == "filluser"
    assert isinstance(payload["skills"], list)
    assert "generated_at" in payload