"""Rudra streaming (SSE) endpoint tests — Gemini stream mocked."""
import pytest

from src import ai


def _login(client, username="streamer", password="pw123456"):
    client.post(
        "/register",
        data={"username": username, "password": password, "confirm": password},
    )
    client.post("/login", data={"username": username, "password": password})


def test_stream_requires_login(client):
    resp = client.post("/rudra/stream", data={"message": "hi"})
    assert resp.status_code == 302


def test_stream_empty_message_redirects(client):
    _login(client)
    resp = client.post("/rudra/stream", data={"message": ""})
    assert resp.status_code == 302


def test_stream_saves_user_and_streams_reply(client, monkeypatch):
    _login(client)

    def fake_stream(messages):
        assert any(m.get("role") == "system" for m in messages)
        yield "Hel"
        yield "lo "
        yield "there"

    monkeypatch.setattr(ai, "gemini_stream", fake_stream)
    resp = client.post("/rudra/stream", data={"message": "hello"})
    assert resp.status_code == 200
    assert resp.mimetype == "text/event-stream"
    body = resp.get_data(as_text=True)
    assert "data: Hel" in body
    assert "data: lo " in body
    assert "data: __DONE__:Hello there" in body


def test_stream_fallback_when_no_reply(client, monkeypatch):
    _login(client)
    monkeypatch.setattr(ai, "gemini_stream", lambda messages: iter(()))
    resp = client.post("/rudra/stream", data={"message": "hello"})
    body = resp.get_data(as_text=True)
    assert "Rudra is offline" in body


def test_stream_history_persisted(client, monkeypatch):
    _login(client)
    from src import db

    def fake_stream(messages):
        yield "ok"

    monkeypatch.setattr(ai, "gemini_stream", fake_stream)
    resp = client.post("/rudra/stream", data={"message": "first"})
    resp.get_data()
    resp = client.post("/rudra/stream", data={"message": "second"})
    resp.get_data()
    history = db.get_chat_history(
        db.get_user_by_username("streamer")["id"]
    )
    roles = [h["role"] for h in history]
    assert roles == ["user", "assistant", "user", "assistant"]