"""Phase 19 — resume system web routes: builder, download, tailor."""
import pytest


def _register_and_login(client):
    client.post(
        "/register",
        data={"username": "resumer", "password": "pw123456", "confirm": "pw123456"},
    )
    client.post("/login", data={"username": "resumer", "password": "pw123456"})


def test_resume_page_requires_login(client):
    resp = client.get("/resume")
    assert resp.status_code == 302


def test_resume_page_renders(client):
    _register_and_login(client)
    resp = client.get("/resume")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Aawara resume" in body
    assert "SKILLS" in body


def test_resume_save_roundtrip(client):
    _register_and_login(client)
    resp = client.post(
        "/resume",
        data={
            "phone": "+919812345678",
            "linkedin": "linkedin.com/in/resumer",
            "education": '[{"title":"B.Tech — CSE — IIT Delhi — 2027"}]',
            "experience": '[{"role":"Intern","company":"Acme","description":"x"}]',
            "projects": "",
            "awards": '["KVPY"]',
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "B.Tech — CSE — IIT Delhi — 2027" in body
    assert "Acme" in body


def test_resume_download_txt(client):
    _register_and_login(client)
    resp = client.get("/resume/download?fmt=txt")
    assert resp.status_code == 200
    assert resp.mimetype == "text/plain"
    assert "resumer" in resp.get_data(as_text=True)


def test_resume_download_pdf(client):
    _register_and_login(client)
    resp = client.get("/resume/download?fmt=pdf")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.get_data()[:4] == b"%PDF"


def test_resume_tailor_route(client):
    _register_and_login(client)
    resp = client.get("/resume/tailor/1")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Tailored resume" in body


def test_resume_tailor_missing_opp_404(client):
    _register_and_login(client)
    resp = client.get("/resume/tailor/9999")
    assert resp.status_code == 404