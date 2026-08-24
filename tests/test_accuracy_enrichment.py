"""Jina-powered hackathon adapters + accuracy enrichment tests.

Fixtures are recorded from real r.jina.ai responses (2026-08-24).
"""
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from src import db
from src.discovery import enrichment, hackathon_sources

FIXTURES = Path(__file__).parent / "fixtures"


def _read_jina(url):
    fixtures = {
        "unstop.com": "sample_unstop_jina.md",
        "dorahacks.io": "sample_dorahacks_jina.md",
        "lablab.ai": "sample_lablab_jina.md",
    }
    for host, fname in fixtures.items():
        if host in url:
            return (FIXTURES / fname).read_text()
    return None


# ---------- Unstop ----------

def test_unstop_adapter_parses_cards(tmp_db):
    entries = hackathon_sources.fetch_hackathons({
        "name": "Unstop", "url": "https://unstop.com/hackathons?oppstatus=open",
        "adapter": "unstop_jina",
    })
    assert len(entries) >= 10
    titles = [e["title"] for e in entries]
    assert any("Hack The Horizon" in t for t in titles)
    # relative windows converted to absolute ISO dates at fetch time
    dated = [e for e in entries if e["deadline"]]
    assert dated, "fixture cards carry 'N days left' windows"
    for e in dated:
        datetime.fromisoformat(e["deadline"])  # must be valid ISO
    # team sizes extracted
    teams = [e["team_size"] for e in entries if e["team_size"]]
    assert any("Members" in t or "Individual" in t for t in teams)


def test_unstop_expired_windows_dropped(tmp_db):
    """A '1 day left' window that already passed today must not be stored."""
    entries = hackathon_sources.fetch_hackathons({
        "name": "Unstop", "url": "https://unstop.com/hackathons",
        "adapter": "unstop_jina",
    })
    today = date.today()
    for e in entries:
        if e["deadline"]:
            assert datetime.fromisoformat(e["deadline"]).date() >= today


# ---------- DoraHacks ----------

def test_dorahacks_adapter_skips_ended_and_extracts_prizes(tmp_db):
    entries = hackathon_sources.fetch_hackathons({
        "name": "DoraHacks", "url": "https://dorahacks.io/hackathon",
        "adapter": "dorahacks_jina",
    })
    assert entries
    urls = [e["url"] for e in entries]
    # the fixture's 'Ended' event (Gensyn/Delphi) must never appear
    assert all(not u.endswith("delphi-agent-competition") for u in urls)
    prizes = [e["prize"] for e in entries if e["prize"]]
    assert any("5,000 USD" in p or "200,000 USD" in p for p in prizes)
    assert all(e["remote"] for e in entries), "all listed as Virtual"


# ---------- lablab ----------

def test_lablab_adapter_extracts_events_and_prizes(tmp_db):
    entries = hackathon_sources.fetch_hackathons({
        "name": "Lablab.ai AI Hackathons", "url": "https://lablab.ai/ai-hackathons",
        "adapter": "lablab_jina",
    })
    assert entries
    slugs = {e["ref"] for e in entries}
    assert "ai-agents-ai-week-hackathon" in slugs
    prizes = [e["prize"] for e in entries if e["prize"]]
    assert any("60,000" in p for p in prizes)


# ---------- enrichment: fill / confirm / conflict ----------

def _seed(overrides=None):
    base = {
        "title": "Accuracy Test Hack", "organization": "Org",
        "type": "hackathon", "application_url": "https://detail.example/page",
        "eligibility_status": "eligible",
    }
    base.update(overrides or {})
    return db.upsert_opportunity(base)


PAGE_WITH_DEADLINE = ("Registration closes on 2026-11-30. "
                      "Prizes and tracks listed below.")


def test_enrichment_fills_missing_deadline(tmp_db, monkeypatch):
    oid = _seed()
    monkeypatch.setattr(enrichment.jina, "read", lambda url: PAGE_WITH_DEADLINE)
    summary = enrichment.run_enrichment(limit=5)
    assert summary["filled"] >= 1
    stored = db.get_opportunity(oid)
    assert stored["deadline"] == "2026-11-30"
    changes = [c for c in db.get_pending_changes()
               if c["change_type"] == "deadline_filled"]
    assert changes and changes[0]["opportunity_id"] == oid


def test_enrichment_conflict_flagged_not_overwritten(tmp_db, monkeypatch):
    oid = _seed({"deadline": "2026-12-15"})
    before = db.get_opportunity(oid)["deadline"]
    monkeypatch.setattr(enrichment.jina, "read",
                        lambda url: "Deadline extended: apply by 2026-12-20.")
    monkeypatch.setattr(
        enrichment, "find_deadline", lambda text: "2027-01-05")
    summary = enrichment.run_enrichment(limit=5)
    assert summary["conflicts"] >= 1
    # stored value untouched — a webpage cannot silently rewrite the DB
    assert db.get_opportunity(oid)["deadline"] == before == "2026-12-15"
    conflicts = [c for c in db.get_pending_changes()
                 if c["change_type"] == "deadline_conflict"]
    assert conflicts and conflicts[0]["old_value"] == "2026-12-15"
    assert conflicts[0]["new_value"] == "2027-01-05"


def test_enrichment_confirm_boosts_verification(tmp_db, monkeypatch):
    oid = _seed({"deadline": "2026-11-30",
                 "organization_trust_score": 95,
                 "verification_status": "pending"})
    monkeypatch.setattr(enrichment.jina, "read", lambda url: PAGE_WITH_DEADLINE)
    summary = enrichment.run_enrichment(limit=5)
    assert summary["confirmed"] >= 1
    stored = db.get_opportunity(oid)
    assert stored["verification_status"] == "verified"


def test_enrichment_handles_unreadable_pages(tmp_db, monkeypatch):
    _seed()
    monkeypatch.setattr(enrichment.jina, "read", lambda url: None)
    summary = enrichment.run_enrichment(limit=5)
    assert summary["unreadable"] >= 1
    assert summary["filled"] == 0


def test_worker_pipeline_reports_enrichment_summary(tmp_db):
    """run_enrichment returns an honest summary block even when idle."""
    s = enrichment.run_enrichment(limit=1)
    for key in ("candidates", "filled", "confirmed", "conflicts",
                "unreadable", "no_change"):
        assert key in s
