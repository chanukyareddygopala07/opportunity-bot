"""Hackathon scout tests: adapters, date parsing, pipeline integration.

Fixtures under tests/fixtures/ are recorded from real source payloads
(devpost.json = live API response; sample_mlh_inertia.json = MLH Inertia
page props).
"""
import json
from pathlib import Path
from unittest import mock

import pytest

from src import db
from src.discovery import hackathon_sources, hackathon_scout

FIXTURES = Path(__file__).parent / "fixtures"


# ---------- shared date parsing ----------

def test_parse_period_devpost_style():
    assert hackathon_sources.parse_period("Jul 31 - Oct 01, 2026") == \
        ("2026-07-31", "2026-10-01")
    assert hackathon_sources.parse_period("Sep 15 - Sep 22, 2026") == \
        ("2026-09-15", "2026-09-22")


def test_parse_date_variants():
    assert hackathon_sources.parse_date("2026-10-01") == "2026-10-01"
    assert hackathon_sources.parse_date("October 1, 2026") == "2026-10-01"
    assert hackathon_sources.parse_date("Oct 01, 2026") == "2026-10-01"
    assert hackathon_sources.parse_date("whenever") is None


# ---------- devpost adapter ----------

class _FakeResponse:
    def __init__(self, body, status=200):
        self._body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def test_devpost_adapter_parses_live_shape(tmp_db, monkeypatch):
    payload = json.loads((FIXTURES / "sample_devpost.json").read_text())

    def fake_fetch(url, **kwargs):
        assert "devpost.com/api/hackathons" in url
        return (json.dumps(payload).encode(), url, 200)

    monkeypatch.setattr(hackathon_sources.fetcher, "fetch_bytes", fake_fetch)
    entries = hackathon_sources.fetch_hackathons({
        "name": "Devpost", "url": "https://devpost.com",
        "adapter": "devpost_api", "max_pages": 1,
    })
    assert entries, "fixture contains open hackathons"
    top = entries[0]
    for field in ("ref", "title", "url", "deadline", "event_start"):
        assert top[field] is not None
    assert top["deadline"] >= top["event_start"]
    online = [e for e in entries if e["remote"]]
    assert online, "fixture includes online hackathons"
    prizes = [e["prize"] for e in entries if e["prize"]]
    assert prizes and prizes[0].startswith("$")


# ---------- mlh adapter ----------

def test_mlh_adapter_reads_inertia_payload(tmp_db, monkeypatch):
    events = json.loads((FIXTURES / "sample_mlh_inertia.json").read_text())
    page_props = {
        "props": {
            "upcomingEvents": events["upcomingEvents"],
            "pastEvents": events["pastEvents"],
        }
    }
    # Mirrors MLH's real markup: <script data-page="app" type="application/json">{...}</script>
    html = ('<html><script data-page="app" type="application/json">'
            + json.dumps(page_props)
            + "</script></html>")

    def fake_fetch(url, **kwargs):
        return (html.encode(), url, 200)

    monkeypatch.setattr(hackathon_sources.fetcher, "fetch_bytes", fake_fetch)
    entries = hackathon_sources.fetch_hackathons({
        "name": "MLH", "adapter": "mlh_inertia", "seasons": ["2026"],
    })
    names = {e["title"] for e in entries}
    assert "HackPrix Season 3" in names
    assert all(e["organization"] == "Major League Hacking" for e in entries)
    hyd = next(e for e in entries if e["title"] == "HackPrix Season 3")
    assert hyd["event_start"] == "2026-10-17"
    assert "India" in (hyd["location"] or "")
    # pastEvents must never be emitted as opportunities
    assert len(entries) == 2


# ---------- internshala adapter ----------

def test_internshala_adapter_extracts_titled_links(tmp_db, monkeypatch):
    html = """
    <div>
      <a href="https://internshala.com/competitions/hackace-2026/"
         title="HackACE 2026: India Innovation Hackathon">x</a>
      <span>Registration Deadline: 30 Sep 2026</span>
      <a href="https://internshala.com/competitions/too-short/"
         title="Go">x</a>
    </div>"""

    def fake_fetch(url, **kwargs):
        return (html.encode(), url, 200)

    monkeypatch.setattr(hackathon_sources.fetcher, "fetch_bytes", fake_fetch)
    entries = hackathon_sources.fetch_hackathons({
        "name": "Internshala",
        "url": "https://internshala.com/competitions/hackathons/",
        "adapter": "internshala_hackathons",
    })
    titles = [e["title"] for e in entries]
    assert any("HackACE" in t for t in titles)
    assert all(e["url"].startswith("https://internshala.com/competitions/")
               for e in entries)


# ---------- full scout path ----------

def _fake_devpost_fetch(payload_file):
    data = (FIXTURES / payload_file).read_bytes()

    def fetch(url, **kwargs):
        return (data, url, 200)
    return fetch


def test_hackathon_scout_end_to_end(tmp_db, monkeypatch):
    monkeypatch.setattr(
        hackathon_sources.fetcher, "fetch_bytes", _fake_devpost_fetch("sample_devpost.json"))
    # verification link checks must not hit the network
    from src import verification
    monkeypatch.setattr(verification, "check_link",
                        lambda url: ("live", "ok"))
    config = {"sources": [{
        "name": "Devpost Hackathons API", "organization": "Devpost",
        "type": "official_program", "category": "hackathon",
        "url": "https://devpost.com/api/hackathons?status=open&page=1",
        "adapter": "devpost_api", "method": "hackathon_json",
        "trust_score": 95, "enabled": True,
        "include_patterns": [], "exclude_patterns": [],
    }]}
    sources_file = tmp_db / "sources.json"
    sources_file.write_text(json.dumps(config))

    count = hackathon_scout.run(category="hackathon",
                                sources_file=str(sources_file))
    assert count > 0

    opps = db.list_opportunities()
    assert all(o["type"] == "hackathon" for o in opps)
    with_deadlines = [o for o in opps if o["deadline"]]
    assert with_deadlines, "devpost fixture carries submission deadlines"

    # second run: everything dedupes, nothing new
    count2 = hackathon_scout.run(category="hackathon",
                                 sources_file=str(sources_file))
    stored = db.list_opportunities()
    assert count2 == 0 or len(stored) == len(opps)


def test_hackathon_entries_without_dates_stay_unknown(tmp_db):
    """Never-guess guarantee: missing deadline stays None, not fabricated."""
    entry = {
        "ref": "mlh:x", "title": "Some Hack", "url": "https://x.example",
        "organization": "Org", "deadline": None,
        "event_start": None, "event_end": None,
        "location": None, "remote": False, "prize": None,
        "themes": [], "team_size": None,
    }
    opp = hackathon_scout.entry_to_opportunity(entry, {"name": "T", "url": "u"})
    assert opp["deadline"] is None
    assert opp["start_date"] is None
    assert opp["type"] == "hackathon"
