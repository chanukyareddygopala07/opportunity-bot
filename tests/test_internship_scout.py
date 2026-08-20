import json
from pathlib import Path

from src import db
from src.discovery import internship_scout

FIXTURES = Path(__file__).parent / "fixtures"


def test_internship_scout_end_to_end(tmp_db, tmp_path):
    gh_uri = (FIXTURES / "sample_greenhouse.json").as_uri()
    ashby_uri = (FIXTURES / "sample_ashby.json").as_uri()
    config = {"sources": [
        {
            "name": "Fixture Greenhouse", "organization": "Example Co",
            "type": "official_company", "category": "internship",
            "url": gh_uri, "method": "ats_greenhouse",
            "trust_score": 100, "enabled": True,
        },
        {
            "name": "Fixture Ashby", "organization": "Example AI",
            "type": "official_company", "category": "internship",
            "url": ashby_uri, "method": "ats_ashby",
            "trust_score": 100, "enabled": True,
        },
    ]}
    sources_file = tmp_path / "sources.json"
    sources_file.write_text(json.dumps(config))

    count = internship_scout.run(category="internship", sources_file=str(sources_file))
    assert count == 2

    opportunities = db.list_opportunities()
    titles = sorted(o["title"] for o in opportunities)
    assert titles == [
        "ML Research Internship",
        "Software Engineering Intern, Security (Summer 2026)",
    ]

    for opp in opportunities:
        assert opp["type"] == "internship"
        assert opp["verification_status"] == "verified"
        assert opp["eligibility_status"] == "likely_eligible"

    ml = next(o for o in opportunities if o["title"] == "ML Research Internship")
    assert ml["category"] == "ai_ml"
    assert ml["remote"] is True
    assert ml["location"] == "Remote"
    assert ml["organization"] == "Example AI"

    security = next(o for o in opportunities if "Security" in o["title"])
    assert security["category"] == "security"
    assert security["remote"] is True

    conn = db.get_connection()
    links = conn.execute("SELECT * FROM opportunity_sources").fetchall()
    logs = conn.execute("SELECT * FROM execution_logs").fetchall()
    conn.close()
    assert len(links) == 2
    assert all(r["status"] == "success" for r in logs)


def test_internship_scout_shared_role_not_stored(tmp_db, tmp_path):
    gh_uri = (FIXTURES / "sample_greenhouse.json").as_uri()
    config = {"sources": [
        {
            "name": "Fixture Greenhouse", "organization": "Example Co",
            "type": "official_company", "category": "internship",
            "url": gh_uri, "method": "ats_greenhouse",
            "trust_score": 100, "enabled": True,
        },
    ]}
    sources_file = tmp_path / "sources.json"
    sources_file.write_text(json.dumps(config))

    internship_scout.run(category="internship", sources_file=str(sources_file))
    titles = [o["title"] for o in db.list_opportunities()]
    assert titles == ["Software Engineering Intern, Security (Summer 2026)"]
    assert "International Account Manager" not in titles
    assert "Backend Engineer (Full-time)" not in titles