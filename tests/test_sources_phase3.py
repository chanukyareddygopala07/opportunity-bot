"""Phase 19 — Aawara source expansion tests.

Covers the Lever ATS adapter, the new source config entries, and the
direct-sources (links-only, never-crawled) page.
"""
import json
import os
from pathlib import Path

import pytest

from src import db
from src.discovery import ats, entries

BASE = Path(__file__).resolve().parent.parent


@pytest.fixture()
def client(tmp_path):
    os.environ["DATABASE_PATH"] = str(tmp_path / "opp.db")
    os.environ["RUN_TOKEN"] = "test-token"
    os.environ["SESSION_SECRET"] = "test-secret"
    from src.webapp import create_app
    application = create_app()
    application.config["TESTING"] = True
    yield application.test_client()
    os.environ.pop("DATABASE_PATH", None)


class TestLeverAdapter:
    def test_parse_lever_list(self):
        data = [
            {
                "id": "a1", "text": "Software Engineering Intern",
                "hostedUrl": "https://jobs.lever.co/spotify/intern",
                "categories": {"location": "Stockholm", "team": "Engineering", "commitment": "Internship"},
                "descriptionPlain": "Build features for Spotify.",
                "createdAt": "2026-08-01T00:00:00Z",
            },
            {
                "id": "a2", "text": "Data Scientist",
                "hostedUrl": "https://jobs.lever.co/spotify/ds",
                "categories": {"location": "Remote", "team": "Data"},
                "descriptionPlain": "Analyze listening trends.",
            },
            {"id": "a3", "text": "", "hostedUrl": None},
        ]
        entries_list = ats.parse_lever(data)
        assert len(entries_list) == 2
        first = entries_list[0]
        assert first["title"] == "Software Engineering Intern"
        assert first["url"] == "https://jobs.lever.co/spotify/intern"
        assert first["remote"] is False
        assert first["employment_type"] == "Internship"

    def test_parse_lever_remote_location(self):
        data = [{
            "id": "b1", "text": "ML Intern",
            "hostedUrl": "https://jobs.lever.co/x/ml",
            "categories": {"location": "Remote anywhere", "team": "ML"},
            "descriptionPlain": "ML research.",
        }]
        entries_list = ats.parse_lever(data)
        assert entries_list[0]["remote"] is True

    def test_parse_lever_not_a_list(self):
        assert ats.parse_lever({}) == []


class TestEntriesRouting:
    def test_lever_is_ats_method(self):
        assert "ats_lever" in entries.ATS_METHODS
        assert "ats_lever" in ats.ATS_FETCHERS


class TestSourceConfig:
    def test_new_sources_present(self):
        data = json.loads((BASE / "config" / "sources.json").read_text())
        names = {s["name"] for s in data["sources"]}
        assert "Spotify Careers API" in names
        assert "EURAXESS Jobs" in names
        assert "AICTE National Internship Portal" in names
        assert "MoSPI Internship Portal" in names
        assert "IISc Bangalore" in names
        assert "Mitacs Globalink" in names
        assert "DAAD India" in names

    def test_blocked_sources_not_in_config(self):
        data = json.loads((BASE / "config" / "sources.json").read_text())
        # Aggregator internship boards stay excluded by policy.
        # Exception: "Internshala Hackathons" (user-directed hackathon
        # listing) — matched below on exact name, not substring.
        blocked = {"LinkedIn", "Indeed", "Naukri", "Glassdoor",
                   "Handshake", "Simplify"}
        names = {s["name"] for s in data["sources"]}
        for name in blocked:
            assert not any(name.lower() in n.lower() for n in names), name
        assert not any(
            n.lower() == "internshala" or
            ("internshala" in n.lower() and "hackathon" not in n.lower())
            for n in names
        ), "only the hackathon-specific Internshala source may exist"

    def test_curated_links_json(self):
        data = json.loads((BASE / "config" / "curated_links.json").read_text())
        groups = data["groups"]
        assert groups
        urls = [item["url"] for g in groups for item in g["items"]]
        assert any("internshala.com" in u for u in urls)
        assert any("linkedin.com" in u for u in urls)
        assert any("workatastartup.com" in u for u in urls)
        assert any("nsf.gov" in u for u in urls)
        assert all(u.startswith("https://") for u in urls)


class TestResourcesPage:
    def test_resources_page_renders(self, client):
        resp = client.get("/resources")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Direct sources" in body
        assert "Internshala" in body
        assert "Aawara" in body