import os
from datetime import datetime, timedelta, timezone

import pytest

from src import db


def _soon(days=14):
    """Dynamic near-future deadline so fixtures never go stale."""
    return (datetime.now(timezone.utc) + timedelta(days=days)).date().isoformat()


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from src.webapp import views
    views._AUTH_ATTEMPTS.clear()
    views._REPORT_ATTEMPTS.clear()
    try:
        import src.api as api_mod
        api_mod._REPORT_ATTEMPTS.clear()
        api_mod._API_ATTEMPTS.clear()
    except (ImportError, AttributeError):
        pass
    yield


@pytest.fixture(autouse=True)
def _isolate_ai_providers(monkeypatch):
    """Keep the suite hermetic: local .env credentials (e.g. a real
    GROQ_API_KEY) must never leak into tests or trigger live API calls.
    Individual tests opt back in via monkeypatch.setenv."""
    from src.webapp.views import _RUDRA_FLAG_CACHE
    for var in ("GROQ_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
                "TELEGRAM_BOT_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    _RUDRA_FLAG_CACHE["value"] = None  # recompute the feature flag per test
    yield


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    db.init_db()
    return tmp_path


def _seed(app):
    db.upsert_opportunity({
        "title": "Software Engineer Intern",
        "organization": "Stripe",
        "type": "internship",
        "location": "Bengaluru, India",
        "remote": 0,
        "match_score": 23,
        "eligibility_status": "eligible",
        "application_url": "https://stripe.example/intern",
        "first_seen": "2026-08-18T00:00:00+00:00",
        "listed_at": "2026-08-18",
    })
    db.upsert_opportunity({
        "title": "Summer Research Fellowship",
        "organization": "IISc",
        "type": "fellowship",
        "location": "Bengaluru, India",
        "remote": 0,
        "match_score": 60,
        "eligibility_status": "likely_eligible",
        "deadline": _soon(14),
        "first_seen": "2026-08-10T00:00:00+00:00",
    })


@pytest.fixture()
def app(tmp_path):
    db_path = str(tmp_path / "opp.db")
    os.environ["DATABASE_PATH"] = db_path
    os.environ["RUN_TOKEN"] = "test-token"
    os.environ["SESSION_SECRET"] = "test-secret"
    from src.webapp import create_app
    application = create_app()
    application.config["TESTING"] = True
    _seed(application)
    yield application
    os.environ.pop("DATABASE_PATH", None)


class CsrfClient:
    """Wraps the Flask test client so every POST carries the correct CSRF
    header (derived exactly like src.webapp.views does server-side)."""

    def __init__(self, client):
        self._client = client

    def post(self, path, **kwargs):
        headers = dict(kwargs.pop("headers", None) or {})
        from src.webapp import auth as webauth
        from src.webapp.views import csrf_token_for
        session = self._client.get_cookie(webauth.SESSION_COOKIE)
        anon = self._client.get_cookie(views_anon_cookie())
        base = None
        if session and session.value:
            base = "session:" + session.value
        elif anon and anon.value:
            base = "anon:" + anon.value
        if base:
            headers.setdefault("X-CSRF-Token", csrf_token_for(base))
        return self._client.post(path, headers=headers, **kwargs)

    def __getattr__(self, name):
        return getattr(self._client, name)


def views_anon_cookie():
    from src.webapp.views import ANON_CSRF_COOKIE
    return ANON_CSRF_COOKIE


@pytest.fixture()
def client(app):
    return CsrfClient(app.test_client())