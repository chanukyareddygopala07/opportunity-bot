"""Phase 8 — application tracking + PWA endpoints."""
import pytest


def _login(client, username="apptrack", password="pw123456"):
    client.post(
        "/register",
        data={"username": username, "password": password, "confirm": password},
    )
    client.post("/login", data={"username": username, "password": password})


def test_manifest_and_sw_public(client):
    resp = client.get("/manifest.json")
    assert resp.status_code == 200
    assert resp.get_json()["short_name"] == "Aawara"
    sw = client.get("/sw.js")
    assert sw.status_code == 200
    assert sw.mimetype == "application/javascript"


def test_applications_requires_login(client):
    assert client.get("/applications").status_code == 302


def test_mark_applied_and_dashboard(client):
    _login(client)
    resp = client.post(
        "/opportunities/1/apply", data={"notes": "sent via Lever"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "applied" in body

    dash = client.get("/applications")
    assert dash.status_code == 200
    body = dash.get_data(as_text=True)
    assert "Software Engineer Intern" in body
    assert "sent via Lever" in body


def test_update_status_and_counts(client):
    _login(client)
    client.post("/opportunities/1/apply")
    client.post("/applications/1/status", data={"status": "interview"})
    client.post("/opportunities/2/apply")
    client.post("/applications/2/status", data={"status": "offer"})
    dash = client.get("/applications")
    body = dash.get_data(as_text=True)
    assert "interview" in body
    assert "offer" in body


def test_invalid_status_rejected(client):
    _login(client)
    client.post("/opportunities/1/apply")
    resp = client.post("/applications/1/status", data={"status": "hacked"})
    assert resp.status_code == 400


def test_delete_application(client):
    _login(client)
    client.post("/opportunities/1/apply")
    resp = client.post(
        "/applications/1/delete", follow_redirects=True
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "No applications tracked yet" in body