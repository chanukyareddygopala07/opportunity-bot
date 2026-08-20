"""Full-text search (FTS5) + richer filter tests."""
import pytest

from src import db
from src.webapp import helpers


@pytest.fixture
def seeded_db(tmp_db):
    db.upsert_opportunity({
        "title": "Software Engineer Intern",
        "organization": "Stripe",
        "type": "internship",
        "location": "Bengaluru, India",
        "remote": 0,
        "eligibility_status": "eligible",
        "application_url": "https://stripe.example/intern",
    })
    db.upsert_opportunity({
        "title": "Summer Research Fellowship",
        "organization": "IISc",
        "type": "fellowship",
        "location": "Bengaluru, India",
        "remote": 0,
        "eligibility_status": "likely_eligible",
        "deadline": "2099-09-01",
    })
    return tmp_db


class TestFtsSearch:
    def test_search_finds_by_title(self, seeded_db):
        ids = db.fts_search_ids("stripe")
        assert len(ids) == 1

    def test_search_finds_by_organization(self, seeded_db):
        ids = db.fts_search_ids("iisc")
        assert len(ids) == 1

    def test_search_multiword_is_and(self, seeded_db):
        db.upsert_opportunity({
            "title": "AI Research Intern",
            "organization": "DeepLabs",
            "type": "internship",
            "application_url": "https://x.example/ai",
        })
        ids = db.fts_search_ids("ai research")
        assert len(ids) == 1
        assert db.fts_search_ids("ai startup") == []

    def test_search_case_insensitive(self, seeded_db):
        assert len(db.fts_search_ids("STRIPE")) == 1

    def test_search_no_terms_returns_none(self, seeded_db):
        assert db.fts_search_ids("") is None
        assert db.fts_search_ids(None) is None
        assert db.fts_search_ids("a") is None


class TestFilterWithFts:
    def test_filter_items_uses_fts(self, seeded_db):
        items = db.list_opportunities()
        got = helpers.filter_items(items, query="iisc")
        assert len(got) == 1
        assert got[0]["organization"] == "IISc"

    def test_filter_items_fts_no_hits_drops_to_substring(self, seeded_db):
        items = db.list_opportunities()
        assert helpers.filter_items(items, query="zzzz-no-such-term") == []

    def test_country_filter(self, seeded_db):
        items = db.list_opportunities()
        got = helpers.filter_items(items, country="india")
        assert len(got) == 2

    def test_country_filter_no_match(self, seeded_db):
        items = db.list_opportunities()
        assert helpers.filter_items(items, country="mars") == []

    def test_remote_filter(self, seeded_db):
        db.upsert_opportunity({
            "title": "Remote ML Intern",
            "organization": "RemoteCo",
            "type": "internship",
            "remote": 1,
            "application_url": "https://x.example/remote",
        })
        items = db.list_opportunities()
        got = helpers.filter_items(items, remote=True)
        assert len(got) == 1
        assert got[0]["remote"] is True

    def test_verified_only_filter(self, seeded_db):
        for opp in db.list_opportunities():
            db.update_opportunity(opp["id"], trust_score=90)
        assert len(helpers.filter_items(db.list_opportunities(), verified_only=True)) == 2
        for opp in db.list_opportunities():
            db.update_opportunity(opp["id"], trust_score=30)
        assert helpers.filter_items(db.list_opportunities(), verified_only=True) == []

    def test_combined_filters(self, seeded_db):
        items = db.list_opportunities()
        got = helpers.filter_items(
            items, query="iisc", country="india", verified_only=False
        )
        assert len(got) == 1