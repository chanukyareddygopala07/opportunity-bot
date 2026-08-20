import json
from pathlib import Path

import pytest

from src import db, schema
from src import sources as registry
from src.discovery import fetcher, parsers

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_feed_extracts_entries():
    text = (FIXTURES / "sample_feed.xml").read_text()
    entries = parsers.parse_feed(text)
    assert len(entries) == 3
    assert entries[0]["title"] == "Call for applications: Summer Research Fellowship 2026"
    assert entries[0]["link"] == "https://example-univ.ac.in/news/summer-research-fellowship-2026"
    assert entries[0]["published"]
    assert entries[0]["description"]


def test_parse_feed_rejects_non_feed():
    with pytest.raises(ValueError):
        parsers.parse_feed("<html><body>not a feed</body></html>")


def test_parse_news_html_extracts_date_title_url():
    html = (FIXTURES / "sample_news.html").read_text()
    items = parsers.parse_news_html(html, "https://www.icts.res.in/announcements")
    assert len(items) == 3
    first = items[0]
    assert first["date"] == "20 April 2026"
    assert first["title"] == "Call for applications - Long Term Visiting Students Program 2027"
    assert first["url"] == "https://www.icts.res.in/news/call-for-applications-ltvsp-2027"
    assert "Research internships" in first["description"]


def test_parse_html_links_deduplicates():
    html = (
        '<html><a href="/a">Alpha</a><a href="/a">Alpha</a>'
        '<a href="/b">Beta</a></html>'
    )
    items = parsers.parse_html_links(html, "https://x.org/")
    assert len(items) == 2


def test_fetcher_reads_file_urls():
    text, final, _status = fetcher.fetch((FIXTURES / "sample_feed.xml").as_uri())
    assert "rss" in text


def test_fetcher_fails_cleanly_on_missing_file(tmp_path):
    with pytest.raises(fetcher.FetchError):
        fetcher.fetch((tmp_path / "nope.xml").as_uri())


def test_source_sync_and_list(tmp_db):
    sources = [
        {
            "name": "Test RSS", "organization": "Test Org", "type": "official_university",
            "category": "fellowship", "url": "https://test.example/feed.xml", "method": "rss",
            "priority": 1, "trust_score": 100, "enabled": True,
            "check_frequency_hours": 6,
            "include_patterns": ["fellow"], "exclude_patterns": ["tender"],
        },
        {
            "name": "Disabled RSS", "organization": "Test Org", "type": "official_university",
            "category": "fellowship", "url": "https://test.example/disabled.xml", "method": "rss",
            "priority": 2, "trust_score": 100, "enabled": False,
        },
    ]
    registry.sync_sources(sources)
    enabled = registry.list_enabled_sources("fellowship")
    assert len(enabled) == 1
    assert enabled[0]["name"] == "Test RSS"
    assert enabled[0]["include_patterns"] == ["fellow"]
    registry.mark_checked(enabled[0]["id"])
    conn = db.get_connection()
    row = conn.execute("SELECT last_checked FROM sources WHERE id = ?", (enabled[0]["id"],)).fetchone()
    conn.close()
    assert row["last_checked"]


def test_scout_end_to_end_against_fixtures(tmp_db, tmp_path, monkeypatch):
    rss_uri = (FIXTURES / "sample_feed.xml").as_uri()
    news_uri = (FIXTURES / "sample_news.html").as_uri()
    config = {"sources": [
        {
            "name": "Fixture RSS", "organization": "Example Univ", "type": "official_university",
            "category": "fellowship", "url": rss_uri, "method": "rss",
            "trust_score": 100, "enabled": True,
            "include_patterns": [], "exclude_patterns": ["tender"],
        },
        {
            "name": "Fixture News", "organization": "ICTS-TIFR", "type": "official_research_lab",
            "category": "fellowship", "url": news_uri, "method": "html_news",
            "trust_score": 95, "enabled": True,
            "include_patterns": ["visiting", "school"], "exclude_patterns": ["selected"],
        },
    ]}
    sources_file = tmp_path / "sources.json"
    sources_file.write_text(json.dumps(config))
    db.upsert_user({
        "country": "India", "degree": "B.Tech", "current_year": 1,
        "branch": None, "graduation_year": None,
        "skills": ["Python"], "interests": ["Research"],
        "preferred": {"paid": True}, "allow": [],
    })
    from src.verification import fetcher as verify_fetcher

    def fake_fetch_bytes(url, **kwargs):
        for fixture in ("sample_feed.xml", "sample_news.html"):
            if fixture in url:
                return (FIXTURES / fixture).read_bytes(), url, 200
        return b"ok", url, 200

    monkeypatch.setattr(verify_fetcher, "fetch_bytes", fake_fetch_bytes)
    from src.discovery import fellowship_scout

    count = fellowship_scout.run(category="fellowship", sources_file=str(sources_file))
    assert count == 4

    opportunities = db.list_opportunities()
    titles = sorted(o["title"] for o in opportunities)
    assert titles == [
        "Call for applications - Long Term Visiting Students Program 2027",
        "Call for applications: Summer Research Fellowship 2026",
        "Summer School on Algorithms",
        "Visiting Student Program for 2nd year undergraduates",
    ]

    statuses = {o["title"]: o["eligibility_status"] for o in opportunities}
    assert statuses["Call for applications: Summer Research Fellowship 2026"] == "eligible"
    assert statuses["Call for applications - Long Term Visiting Students Program 2027"] == "eligible"
    assert statuses["Visiting Student Program for 2nd year undergraduates"] == "not_eligible"
    assert statuses["Summer School on Algorithms"] == "unclear"

    for opp in opportunities:
        assert opp["verification_status"] == "verified"
        assert opp["organization_trust_score"] in (95, 100)
        assert opp["application_url"] == opp["source_url"]
        assert opp["type"] == "fellowship"

    conn = db.get_connection()
    links = conn.execute("SELECT * FROM opportunity_sources").fetchall()
    logs = conn.execute("SELECT * FROM execution_logs").fetchall()
    conn.close()
    assert len(links) == 4
    assert all(r["status"] == "success" for r in logs)


def test_scout_deduplicates_across_sources(tmp_db, tmp_path):
    rss_uri = (FIXTURES / "sample_feed.xml").as_uri()
    rss_dup_uri = (FIXTURES / "sample_feed_dup.xml").as_uri()
    config = {"sources": [
        {
            "name": "Fixture RSS A", "organization": "Example Univ", "type": "official_university",
            "category": "fellowship", "url": rss_uri, "method": "rss",
            "trust_score": 100, "enabled": True, "include_patterns": ["summer"],
        },
        {
            "name": "Fixture RSS B", "organization": "Example Univ", "type": "official_university",
            "category": "fellowship", "url": rss_dup_uri, "method": "rss",
            "trust_score": 100, "enabled": True, "include_patterns": ["summer"],
        },
    ]}
    sources_file = tmp_path / "sources.json"
    sources_file.write_text(json.dumps(config))
    from src.discovery import fellowship_scout

    fellowship_scout.run(category="fellowship", sources_file=str(sources_file))
    assert len(db.list_opportunities()) == 1
    conn = db.get_connection()
    links = conn.execute("SELECT source_id FROM opportunity_sources").fetchall()
    conn.close()
    assert len(links) == 2


def test_opportunity_from_fixture_validates_clean(tmp_db, tmp_path):
    rss_uri = (FIXTURES / "sample_feed.xml").as_uri()
    config = {"sources": [
        {
            "name": "Fixture RSS", "organization": "Example Univ", "type": "official_university",
            "category": "fellowship", "url": rss_uri, "method": "rss",
            "trust_score": 100, "enabled": True, "include_patterns": ["summer"],
        },
    ]}
    sources_file = tmp_path / "sources.json"
    sources_file.write_text(json.dumps(config))
    from src.discovery import fellowship_scout

    fellowship_scout.run(category="fellowship", sources_file=str(sources_file))
    opp = db.list_opportunities()[0]
    errors, warnings = schema.validate_opportunity(opp)
    assert errors == []