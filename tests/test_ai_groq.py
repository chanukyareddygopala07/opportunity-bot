"""Groq provider integration tests (OpenAI-compatible wire format)."""
import json
import urllib.request

import pytest

from src import ai


@pytest.fixture(autouse=True)
def _groq_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-123")
    monkeypatch.setenv("GROQ_MODEL", "llama-test")
    yield
    monkeypatch.delenv("GROQ_API_KEY", raising=False)


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body

    def __iter__(self):
        for line in self._body.split(b"\n"):
            yield line


def test_configured_providers_includes_groq(monkeypatch):
    monkeypatch.setattr(ai, "is_available", lambda *a, **k: False)
    assert "groq" in ai.configured_providers()


def test_groq_chat_parses_openai_style_reply(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["payload"] = json.loads(req.data.decode())
        captured["auth"] = req.headers.get("Authorization")
        return _FakeResponse(json.dumps({
            "choices": [{"message": {"content": "hello from groq"}}]
        }).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    reply, provider = ai.chat_ask(
        [{"role": "user", "content": "hi"}], profile=None)
    assert reply == "hello from groq"
    assert provider == "groq"
    assert captured["url"].startswith("https://api.groq.com/openai/v1/")
    assert captured["payload"]["model"] == "llama-test"
    assert captured["auth"] == "Bearer test-key-123"
    # privacy: chat_ask builds its own system message; no stray secrets
    assert all(m["role"] in ("system", "user", "assistant")
               for m in captured["payload"]["messages"])


def test_groq_stream_yields_deltas_and_stops_on_done(monkeypatch):
    sse_body = b"\n".join([
        b'data: {"choices": [{"delta": {"content": "Hel"}}]}',
        b'data: {"choices": [{"delta": {"content": "lo"}}]}',
        b"data: [DONE]",
        b"",
    ])

    def fake_urlopen(req, timeout=None):
        return _FakeResponse(sse_body)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    fragments = list(ai.groq_stream([{"role": "user", "content": "hi"}]))
    assert fragments == ["Hel", "lo"]


def test_groq_stream_error_ends_cleanly(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert list(ai.groq_stream([{"role": "user", "content": "hi"}])) == []


def test_groq_failure_falls_through_to_gemini(tmp_db, monkeypatch):
    """When Groq errors, chat_ask must try the next provider."""
    def failing_urlopen(req, timeout=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(urllib.request, "urlopen", failing_urlopen)
    monkeypatch.setattr(ai, "_gemini_chat",
                        lambda messages, timeout=60: ("gemini!", "gemini"))
    monkeypatch.setattr(ai, "is_available", lambda *a, **k: False)
    reply, provider = ai.chat_ask([{"role": "user", "content": "hi"}],
                                  profile=None)
    assert (reply, provider) == ("gemini!", "gemini")


def test_rudra_stream_uses_groq_first(tmp_db, client, monkeypatch):
    """End-to-end: the Rudra SSE path streams via Groq when the key is set."""
    import src.ai as ai_mod
    from src.webapp.views import csrf_token_for
    from src.webapp import auth as webauth

    monkeypatch.setattr(ai_mod, "groq_stream",
                        lambda messages: iter(["Hi! ", "I'm Groq-backed."]))
    gemini_called = {"used": False}

    def fake_gemini(messages):
        gemini_called["used"] = True
        return iter(())

    monkeypatch.setattr(ai_mod, "gemini_stream", fake_gemini)
    monkeypatch.setattr(ai_mod, "chat_ask",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError))

    client.post("/register", data={"username": "groquser",
                                   "password": "longenough1",
                                   "confirm": "longenough1"})
    token = client.get_cookie(webauth.SESSION_COOKIE).value
    headers = {"X-CSRF-Token": csrf_token_for("session:" + token),
               "Content-Type": "application/json"}
    resp = client.post("/rudra/api/chat", headers=headers,
                       data=json.dumps({"message": "hello"}))
    events = [json.loads(line[len("data: "):]) for line in
              resp.get_data(as_text=True).split("\n") if line.startswith("data: ")]
    kinds = [e["type"] for e in events]
    assert "delta" in kinds
    done = [e for e in events if e["type"] == "done"][0]
    assert done["provider"] == "groq"
    assert gemini_called["used"] is False
