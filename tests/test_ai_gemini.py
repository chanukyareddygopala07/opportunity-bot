"""Gemini provider tests for Rudra (mocked, no network)."""
import json

from src import ai


def test_gemini_requires_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert ai._gemini_chat([{"role": "user", "content": "hi"}]) == (None, None)


def test_gemini_call_shape(monkeypatch):
    captured = {}

    class FakeResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({
                "candidates": [{
                    "content": {"parts": [{"text": "Hello from Gemini."}]},
                }]
            }).encode()

    class FakeReq:
        def __init__(self, url, data=None, method=None, headers=None):
            captured["url"] = url
            captured["data"] = json.loads(data.decode())
            captured["headers"] = headers

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(ai.urllib.request, "Request", FakeReq)
    monkeypatch.setattr(ai.urllib.request, "urlopen", lambda req, timeout=60: FakeResp())

    reply, provider = ai._gemini_chat([
        {"role": "system", "content": "Be terse."},
        {"role": "user", "content": "hi"},
    ])
    assert provider == "gemini"
    assert reply == "Hello from Gemini."
    assert "generateContent" in captured["url"]
    assert captured["headers"]["x-goog-api-key"] == "test-key"
    assert captured["data"]["system_instruction"]["parts"][0]["text"] == "Be terse."
    assert captured["data"]["contents"][0]["parts"][0]["text"] == "hi"


def test_gemini_maps_assistant_role(monkeypatch):
    captured = {}

    class FakeResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({
                "candidates": [{"content": {"parts": [{"text": "ok"}]}}]
            }).encode()

    class FakeReq:
        def __init__(self, url, data=None, method=None, headers=None):
            captured["data"] = json.loads(data.decode())

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(ai.urllib.request, "Request", FakeReq)
    monkeypatch.setattr(ai.urllib.request, "urlopen", lambda req, timeout=60: FakeResp())

    _, _ = ai._gemini_chat([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "yo"},
    ])
    roles = [c["role"] for c in captured["data"]["contents"]]
    assert roles == ["user", "model"]


def test_chat_ask_uses_gemini_when_key_set(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(ai, "_openai_chat", lambda messages, timeout=60: (None, None))
    monkeypatch.setattr(ai, "_gemini_chat", lambda messages, timeout=60: ("Gemini reply", "gemini"))
    monkeypatch.setattr(ai, "is_available", lambda: False)
    reply, provider = ai.chat_ask([{"role": "user", "content": "help"}])
    assert (reply, provider) == ("Gemini reply", "gemini")


def test_chat_ask_openai_first_then_gemini(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setattr(ai, "_openai_chat", lambda messages, timeout=60: ("OpenAI reply", "openai"))
    reply, provider = ai.chat_ask([{"role": "user", "content": "help"}])
    assert (reply, provider) == ("OpenAI reply", "openai")