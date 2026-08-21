import os

from src import db

EXPECTED_TABLES = {
    "users", "opportunities", "sources", "opportunity_sources",
    "eligibility_results", "scores", "notifications", "deadlines",
    "execution_logs", "search_queries", "system_errors", "duplicates",
    "verifications", "ai_assessments", "sessions", "bookmarks",
    "discovery_runs", "source_health", "filtering_decisions", "raw_responses",
    "chat_messages", "applications", "crawl_jobs", "reports", "opportunities_fts",
    "user_views",
    "agent_tasks", "agent_events", "agent_metrics",
    "opportunity_evidence", "opportunity_changes",
}

SAMPLE_OPP = {
    "title": "XYZ Research Internship",
    "organization": "XYZ Labs",
    "type": "internship",
    "category": "research",
    "deadline": "2026-09-15",
    "application_url": "https://example.com/apply",
    "remote": True,
    "eligible_countries": ["India", "USA"],
    "requirements": ["C++", "Git"],
    "preferred_skills": ["Python"],
    "match_score": 94,
    "eligibility_status": "eligible",
    "funding": "Paid",
    "stipend": "$2000/mo",
}


def test_init_creates_all_tables(tmp_db):
    conn = db.get_connection()
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "AND name NOT LIKE 'opportunities_fts_%'"
    ).fetchall()
    conn.close()
    assert {r["name"] for r in rows} == EXPECTED_TABLES


def test_upsert_deduplicates_by_key(tmp_db):
    db.upsert_opportunity(SAMPLE_OPP)
    db.upsert_opportunity(SAMPLE_OPP)
    assert len(db.list_opportunities()) == 1


def test_upsert_second_seen_updates_last_seen(tmp_db):
    db.upsert_opportunity(SAMPLE_OPP)
    first = db.list_opportunities()[0]
    updated = dict(SAMPLE_OPP)
    updated["funding"] = "Fully funded"
    db.upsert_opportunity(updated)
    after = db.list_opportunities()[0]
    assert after["funding"] == "Fully funded"
    assert after["last_seen"] >= first["last_seen"]
    assert len(db.list_opportunities()) == 1


def test_opportunity_json_fields_roundtrip(tmp_db):
    db.upsert_opportunity(SAMPLE_OPP)
    opp = db.list_opportunities()[0]
    assert opp["eligible_countries"] == ["India", "USA"]
    assert opp["requirements"] == ["C++", "Git"]
    assert opp["remote"] is True
    assert opp["saved"] is False


def test_opportunity_with_null_url_and_deadline_roundtrip(tmp_db):
    opp = dict(SAMPLE_OPP)
    opp["application_url"] = None
    opp["deadline"] = None
    db.upsert_opportunity(opp)
    db.upsert_opportunity(opp)
    assert len(db.list_opportunities()) == 1


def test_update_opportunity_fields(tmp_db):
    opp_id = db.upsert_opportunity(SAMPLE_OPP)
    db.update_opportunity(opp_id, match_score=88, eligibility_status="unclear", saved=1)
    opp = db.get_opportunity(opp_id)
    assert opp["match_score"] == 88
    assert opp["eligibility_status"] == "unclear"
    assert opp["saved"] is True


def test_user_seed_and_update(tmp_db):
    user_id = db.upsert_user({
        "country": "India", "degree": "B.Tech", "current_year": 1,
        "skills": ["C", "Python"], "interests": ["ML"],
    })
    db.upsert_user({"country": "India", "degree": "B.Tech", "current_year": 2, "skills": ["C"]}, chat_id=123)
    user = db.get_default_user()
    assert user["id"] == user_id
    assert user["current_year"] == 2
    assert user["skills"] == ["C"]


def test_deadline_and_notification_logging(tmp_db):
    opp_id = db.upsert_opportunity(SAMPLE_OPP)
    db.upsert_deadline(opp_id, "2026-09-15")
    db.upsert_deadline(opp_id, "2026-09-15")
    db.mark_deadline_notified(opp_id, "notified_7d")
    conn = db.get_connection()
    row = conn.execute("SELECT * FROM deadlines WHERE opportunity_id = ?", (opp_id,)).fetchone()
    conn.close()
    assert row["notified_7d"] == 1
    assert row["notified_30d"] == 0


def test_error_and_execution_logging(tmp_db):
    db.log_error("extraction", "HTTPError", "404 from source")
    db.log_execution("run-1", "02_source_discovery", "fetch", "failed", "timeout")
    conn = db.get_connection()
    errors = conn.execute("SELECT * FROM system_errors").fetchall()
    logs = conn.execute("SELECT * FROM execution_logs").fetchall()
    conn.close()
    assert len(errors) == 1
    assert errors[0]["component"] == "extraction"
    assert len(logs) == 1
    assert logs[0]["status"] == "failed"


def test_list_filter_by_type(tmp_db):
    db.upsert_opportunity(SAMPLE_OPP)
    db.upsert_opportunity({**SAMPLE_OPP, "title": "ABC Fellowship", "type": "fellowship", "application_url": "https://example.com/fell"})
    internships = db.list_opportunities(opp_type="intern")
    fellowships = db.list_opportunities(opp_type="fellow")
    assert len(internships) == 1
    assert len(fellowships) == 1