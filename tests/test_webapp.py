"""Phase 17 — web front-end tests: auth, pages, bookmarks, pipeline hook."""
import os

from src import db
from src.webapp import auth, helpers

TMP_DB = os.environ.get("TMP_DB", "/tmp/opp.db")


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


def _register(client, username="student1", password="hunter22pw"):
    return client.post(
        "/register",
        data={"username": username, "password": password, "confirm": password},
        follow_redirects=False,
    )


def test_index_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "AAWARA" in body
    assert "Software Engineer Intern" in body


def test_register_creates_user_and_session(client):
    resp = _register(client)
    assert resp.status_code == 302
    assert auth.SESSION_COOKIE in resp.headers.get("Set-Cookie", "")
    assert db.get_user_by_username("student1") is not None
    assert db.get_user_by_username("student1")["password_hash"].startswith("scrypt$")


def test_register_validation(client):
    resp = client.post(
        "/register",
        data={"username": "ab", "password": "x", "confirm": "y"},
    )
    assert b"Username must be" in resp.get_data()
    assert db.get_user_by_username("ab") is None


def test_login_wrong_password(client):
    _register(client)
    client.post("/logout")
    resp = client.post(
        "/login", data={"username": "student1", "password": "wrong-pass"}
    )
    assert b"Invalid username or password" in resp.get_data()


def test_login_success_and_logout(client):
    _register(client)
    client.post("/logout")
    resp = client.post("/login", data={"username": "student1", "password": "hunter22pw"})
    assert resp.status_code == 302
    assert "Set-Cookie" in resp.headers


def test_saved_requires_login(client):
    resp = client.get("/saved")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_save_and_unsave_bookmark(client):
    _register(client)
    opp_id = db.list_opportunities()[0]["id"]
    resp = client.post(f"/o/{opp_id}/save", follow_redirects=False)
    assert resp.status_code == 302
    assert db.is_bookmarked(db.get_user_by_username("student1")["id"], opp_id)
    assert client.get("/saved").status_code == 200
    client.post(f"/o/{opp_id}/unsave")
    assert not db.is_bookmarked(db.get_user_by_username("student1")["id"], opp_id)


def _by_title(app, title):
    return next(o for o in db.list_opportunities() if o["title"] == title)


def test_detail_page_and_404(app, client):
    opp_id = _by_title(app, "Software Engineer Intern")["id"]
    resp = client.get(f"/o/{opp_id}")
    assert resp.status_code == 200
    assert b"Stripe" in resp.get_data()
    assert client.get("/o/999999").status_code == 404


def test_list_pages_and_filters(client):
    assert client.get("/opportunities").status_code == 200
    resp = client.get("/internships")
    body = resp.get_data(as_text=True)
    assert "Software Engineer Intern" in body
    assert "Summer Research Fellowship" not in body
    resp = client.get("/fellowships")
    assert "Summer Research Fellowship" in resp.get_data(as_text=True)
    resp = client.get("/opportunities?q=research")
    assert "Summer Research Fellowship" in resp.get_data(as_text=True)


def test_top_urgent_stats_pages(client):
    assert client.get("/top").status_code == 200
    assert client.get("/urgent").status_code == 200
    resp = client.get("/stats")
    assert resp.status_code == 200
    assert b"opportunities stored" in resp.get_data()


def test_profile_update(client):
    _register(client)
    resp = client.post(
        "/profile",
        data={
            "country": "India", "citizenship": "Indian",
            "degree": "B.Tech", "degree_level": "Undergraduate",
            "current_year": "3", "university": "IIT",
            "branch": "CSE", "graduation_year": "2028",
            "skills": "Python, DSA", "interests": "AI, Research",
            "eligible_years": "2,3,4",
        },
    )
    assert resp.status_code == 200
    user = db.get_user_by_username("student1")
    assert user["current_year"] == 3
    assert user["skills"] == ["Python", "DSA"]
    assert user["eligible_years"] == [2, 3, 4]
    assert b"3" in client.get("/profile").get_data()


def test_run_requires_token(client, monkeypatch):
    called = []

    def fake_run():
        called.append(True)
        return {"ok": True}

    monkeypatch.setattr("src.webapp.views.worker.run_pipeline", fake_run)
    assert client.post("/run").status_code == 401
    resp = client.post("/run", headers={"X-Run-Token": "test-token"})
    assert resp.status_code == 200
    assert called
    assert client.get("/health").status_code == 200


def test_password_hash_roundtrip():
    hashed = auth.hash_password("secret-pass")
    assert auth.verify_password("secret-pass", hashed)
    assert not auth.verify_password("nope", hashed)
    assert not auth.verify_password("secret-pass", None)


def test_helpers_filter_and_paginate(app):
    items = db.list_opportunities()
    assert len(helpers.filter_items(items, opp_type="internship")) == 1
    assert len(helpers.filter_items(items, query="iisc")) == 1
    page_items, page, pages, total = helpers.paginate(items, 1)
    assert page == 1 and pages == 1 and total == 2
    user = db.get_user_by_username("student1") or {
        "country": "India", "degree": "B.Tech", "current_year": 2,
        "branch": "CSE", "skills": ["Python"], "interests": ["AI"],
    }
    scored = helpers.score_items(items, user)
    assert scored and scored[0][1] is not None


def test_classify(app):
    opp = _by_title(app, "Summer Research Fellowship")
    assert helpers.classify(opp) == "fellowship"
    assert helpers.classify(_by_title(app, "Software Engineer Intern")) == "internship"