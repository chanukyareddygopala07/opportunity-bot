"""Verification v2 tests — official priority, scheduling, due pipeline, reports."""
from datetime import datetime, timedelta, timezone

from src import db, verification


def _soon():
    """Deadline 3 days out (dynamic — never stale)."""
    return (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat()


def _seed_opp(deadline=None, official_url=None, application_url="https://x.example/a"):
    return db.upsert_opportunity({
        "title": "T", "organization": "Org", "type": "internship",
        "deadline": deadline, "official_url": official_url,
        "application_url": application_url,
    })


class TestSchedule:
    def test_weekly_when_verified(self, tmp_db):
        opp_id = _seed_opp()
        opp = db.get_opportunity(opp_id)
        verification.schedule_next_verification(opp, "verified")
        next_at = db.get_opportunity(opp_id)["next_verification"]
        days = (datetime.fromisoformat(next_at) - datetime.now(timezone.utc)).total_seconds()
        assert timedelta(days=6) < timedelta(seconds=days) < timedelta(days=8)

    def test_twelve_hours_when_deadline_within_week(self, tmp_db):
        opp_id = _seed_opp(deadline=_soon())
        opp = db.get_opportunity(opp_id)
        verification.schedule_next_verification(opp, "unverified")
        next_at = db.get_opportunity(opp_id)["next_verification"]
        hours = (datetime.fromisoformat(next_at) - datetime.now(timezone.utc)).total_seconds() / 3600
        assert 10 <= hours <= 14

    def test_daily_when_unverified(self, tmp_db):
        opp_id = _seed_opp()
        opp = db.get_opportunity(opp_id)
        verification.schedule_next_verification(opp, "unverified")
        next_at = db.get_opportunity(opp_id)["next_verification"]
        hours = (datetime.fromisoformat(next_at) - datetime.now(timezone.utc)).total_seconds() / 3600
        assert 22 <= hours <= 26


class TestDue:
    def test_unverified_items_are_due(self, tmp_db):
        _seed_opp()
        due = db.get_due_verifications(10)
        assert len(due) == 1

    def test_scheduled_future_item_not_due(self, tmp_db):
        opp_id = _seed_opp()
        future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        db.update_opportunity(opp_id, next_verification=future)
        assert db.get_due_verifications(10) == []

    def test_deadline_items_come_first(self, tmp_db):
        far_id = _seed_opp(deadline="2099-01-01")
        soon_id = _seed_opp(deadline=_soon())
        due = db.get_due_verifications(10)
        assert due[0]["id"] == soon_id
        assert due[1]["id"] == far_id

    def test_verify_due_runs_and_schedules(self, tmp_db, monkeypatch):
        opp_id = _seed_opp()
        monkeypatch.setattr(verification, "check_link", lambda url: ("live", "ok"))
        monkeypatch.setattr(verification, "_source_count", lambda oid: 0)
        db.update_opportunity(opp_id, organization_trust_score=95)
        counts = verification.verify_due(10)
        assert counts.get("verified") == 1
        assert db.get_opportunity(opp_id)["next_verification"] is not None
        assert db.get_opportunity(opp_id)["verification_status"] == "verified"


class TestReports:
    def test_add_and_list(self, tmp_db):
        opp_id = _seed_opp()
        rid = db.add_report(opp_id, None, "Deadline is wrong", "actually 2027")
        reports = db.list_reports()
        assert len(reports) == 1
        assert reports[0]["id"] == rid
        assert reports[0]["title"] == "T"
        assert reports[0]["reason"] == "Deadline is wrong"
        assert reports[0]["status"] == "pending"

    def test_resolve(self, tmp_db):
        opp_id = _seed_opp()
        rid = db.add_report(opp_id, None, "Other")
        db.resolve_report(rid, "accepted")
        assert db.list_reports() == []
        assert db.list_reports(status="accepted")[0]["status"] == "accepted"