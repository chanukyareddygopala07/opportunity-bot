import os

import pytest

from src import db


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
        "deadline": "2026-09-01",
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


@pytest.fixture()
def client(app):
    return app.test_client()