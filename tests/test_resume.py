"""Tests for the fact-locked resume builder + tailor (Phase 19)."""
import os
import uuid

import pytest

from src import db, resume


@pytest.fixture
def user(tmp_path, monkeypatch):
    os.environ["DATABASE_PATH"] = str(tmp_path / "opp.db")
    db.init_db()
    email = f"aisha{uuid.uuid4().hex[:8]}@example.com"
    uid = db.create_user(
        username="Aisha",
        email=email,
        password_hash="x",
        profile={
            "degree": "B.Tech",
            "branch": "Computer Science",
            "university": "IIT Bombay",
            "graduation_year": 2027,
            "skills": ["Python", "Docker", "SQL", "R"],
            "interests": ["AI/ML", "Research"],
        },
    )
    user = db.get_user_by_id(uid)
    db.update_user_fields(uid, {"cgpa": 8.6})
    user = db.get_user_by_id(uid)
    yield user


def test_profile_resume_is_fact_locked(user):
    built = resume.profile_resume(user)
    assert built["name"] == "Aisha"
    assert built["education"] == [
        {"title": "B.Tech — Computer Science — IIT Bombay — 2027 · CGPA 8.6"}
    ]
    assert built["skills"] == ["Python", "Docker", "SQL", "R"]
    assert built["experience"] == []
    assert built["contact"] == {"email": user["email"]}


def test_profile_resume_contact_and_extra(user):
    db.save_user_resume(user["id"], {
        "contact": {"phone": "+919000000000", "linkedin": "linkedin.com/in/aisha"},
        "experience": [{"role": "SWE Intern", "company": "Acme",
                        "description": "Built a pipeline."}],
        "education": [{"title": "B.Tech — CSE — IIT Bombay — 2027"}],
    })
    built = resume.profile_resume(db.get_user_by_id(user["id"]))
    assert built["contact"]["phone"] == "+919000000000"
    assert built["experience"][0]["company"] == "Acme"
    assert len(built["education"]) == 1
    assert built["education"][0]["title"] == "B.Tech — CSE — IIT Bombay — 2027"


def test_tailor_reorders_matched_skills(user):
    built = resume.profile_resume(user)
    tailored, notes = resume.tailor(
        built, job_text="We need Python and SQL skills for data work."
    )
    assert tailored["skills"][:2] == ["Python", "SQL"]
    assert set(tailored["skills"]) == {"Python", "Docker", "SQL", "R"}
    assert any("reordered skills" in n for n in notes)


def test_tailor_never_adds_unlisted_skills(user):
    built = resume.profile_resume(user)
    tailored, notes = resume.tailor(
        built, job_text="Must know Kubernetes, Go and Rust."
    )
    assert tailored["skills"] == ["Python", "Docker", "SQL", "R"]
    assert any("no listed skills matched" in n for n in notes)


def test_tailor_preserves_all_sections(user):
    db.save_user_resume(user["id"], {
        "projects": [{"title": "Port scanner", "year": "2025",
                      "description": "Scans 1000 hosts/min."}],
    })
    built = resume.profile_resume(db.get_user_by_id(user["id"]))
    tailored, _ = resume.tailor(built, job_text="Python")
    assert tailored["projects"][0]["title"] == "Port scanner"
    assert tailored["name"] == "Aisha"


def test_render_text_ats_clean(user):
    built = resume.profile_resume(user)
    text = resume.render_text(built)
    assert "Aisha" in text
    assert "SKILLS" in text
    assert "Python, Docker, SQL, R" in text
    assert "IIT Bombay" in text
    assert "*" not in text and "|" not in text and "#" not in text


def test_tailor_uses_opportunity_text(user):
    built = resume.profile_resume(user)
    opp = {"title": "Data Intern", "description": "Python + SQL pipelines"}
    tailored, _ = resume.tailor(built, opportunity=opp)
    assert tailored["skills"][:2] == ["Python", "SQL"]


def test_render_pdf(user):
    built = resume.profile_resume(user)
    path = resume.render_pdf(built, path="/tmp/aawara_test_resume.pdf")
    with open(path, "rb") as fh:
        assert fh.read(4) == b"%PDF"