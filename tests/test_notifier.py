from datetime import date

import pytest

from src import db
from src.notifications import notifier
from src.notifications.notifier import bucket_for


class TestBucketFor:
    def test_tightest_bucket(self):
        assert bucket_for(25) == "notified_30d"
        assert bucket_for(10) == "notified_14d"
        assert bucket_for(5) == "notified_7d"
        assert bucket_for(2) == "notified_3d"
        assert bucket_for(1) == "notified_24h"
        assert bucket_for(0) == "notified_24h"

    def test_expired_or_unknown(self):
        assert bucket_for(-1) is None
        assert bucket_for(None) is None


def _seed_user(chat_id=12345):
    db.upsert_user({
        "country": "India", "degree": "B.Tech",
        "current_year": 1, "branch": None, "graduation_year": None,
        "skills": ["Python"], "interests": ["Research"],
        "preferred": {"paid": True}, "allow": [],
    }, chat_id=chat_id)
    return db.get_user_by_chat(chat_id)


def _opp(**overrides):
    opp = {
        "title": "ML Research Intern",
        "organization": "Modal",
        "type": "internship",
        "category": "ai_ml",
        "application_url": "https://modal.com/careers",
        "match_score": 80,
        "verification_status": "verified",
        "eligibility_status": "eligible",
    }
    opp.update(overrides)
    return db.upsert_opportunity(opp)


class TestSendNewOpportunities:
    def _send(self, monkeypatch):
        sent = []

        def fake_send(text, chat_id=None, token=None, parse_mode="HTML"):
            sent.append((chat_id, text))
            return {"ok": True}

        monkeypatch.setattr(notifier, "SENDER", fake_send)
        return sent

    def test_notifies_high_value_opportunity(self, tmp_db, monkeypatch):
        user = _seed_user()
        opp_id = _opp()
        sent = self._send(monkeypatch)
        assert notifier.send_new_opportunities(user) == 1
        assert len(sent) == 1
        assert sent[0][0] == 12345 or str(sent[0][0]) == "12345"
        assert "ML Research Intern" in sent[0][1]
        conn = db.get_connection()
        row = conn.execute(
            "SELECT * FROM notifications WHERE opportunity_id = ?", (opp_id,)
        ).fetchone()
        conn.close()
        assert row["kind"] == "new_opportunity"
        assert row["delivered"] == 1

    def test_idempotent(self, tmp_db, monkeypatch):
        user = _seed_user()
        _opp()
        self._send(monkeypatch)
        notifier.send_new_opportunities(user)
        assert notifier.send_new_opportunities(user) == 0

    def test_low_score_skipped(self, tmp_db, monkeypatch):
        user = _seed_user()
        opp_id = _opp(match_score=20)
        sent = self._send(monkeypatch)
        assert notifier.send_new_opportunities(user) == 0
        assert sent == []
        conn = db.get_connection()
        row = conn.execute(
            "SELECT id FROM notifications WHERE opportunity_id = ?", (opp_id,)
        ).fetchone()
        conn.close()
        assert row is None

    def test_not_eligible_skipped(self, tmp_db, monkeypatch):
        user = _seed_user()
        opp_id = _opp(eligibility_status="not_eligible")
        sent = self._send(monkeypatch)
        assert notifier.send_new_opportunities(user) == 0
        assert sent == []

    def test_unverified_skipped(self, tmp_db, monkeypatch):
        user = _seed_user()
        opp_id = _opp(verification_status="pending")
        sent = self._send(monkeypatch)
        assert notifier.send_new_opportunities(user) == 0
        assert sent == []

    def test_official_allowed(self, tmp_db, monkeypatch):
        user = _seed_user()
        _opp(verification_status="official")
        sent = self._send(monkeypatch)
        assert notifier.send_new_opportunities(user) == 1
        assert len(sent) == 1

    def test_no_chat_id_skips_without_crash(self, tmp_db, monkeypatch):
        _opp()
        sent = self._send(monkeypatch)
        assert notifier.send_new_opportunities({"chat_id": None}) == 0
        assert sent == []

    def test_dry_run_is_pure(self, tmp_db):
        user = _seed_user()
        opp_id = _opp()
        assert notifier.send_new_opportunities(user, dry_run=True) == 1
        conn = db.get_connection()
        row = conn.execute(
            "SELECT id FROM notifications WHERE opportunity_id = ?", (opp_id,)
        ).fetchone()
        conn.close()
        assert row is None
        assert notifier.send_new_opportunities(user) == 1

    def test_send_failure_recorded(self, tmp_db, monkeypatch):
        user = _seed_user()

        def boom(text, chat_id=None, token=None, parse_mode="HTML"):
            raise RuntimeError("network down")

        monkeypatch.setattr(notifier, "SENDER", boom)
        opp_id = _opp()
        assert notifier.send_new_opportunities(user) == 1
        conn = db.get_connection()
        row = conn.execute(
            "SELECT delivered FROM notifications WHERE opportunity_id = ?", (opp_id,)
        ).fetchone()
        conn.close()
        assert row["delivered"] == 0


class TestDeadlineReminders:
    def _seed_deadline(self, deadline, eligibility="eligible", title="Scheme X"):
        opp_id = db.upsert_opportunity({
            "title": title,
            "organization": "Org",
            "type": "fellowship",
            "application_url": "https://org.example/apply",
            "match_score": 70,
            "verification_status": "verified",
            "eligibility_status": eligibility,
            "deadline": deadline,
        })
        db.upsert_deadline(opp_id, deadline)
        return opp_id

    def _freeze_days_left(self, monkeypatch, frozen_today):
        monkeypatch.setattr(
            notifier.formatting, "deadline_days_left",
            lambda deadline_str, today=None: (date.fromisoformat(deadline_str) - frozen_today).days,
        )

    def _send(self, monkeypatch):
        sent = []

        def fake_send(text, chat_id=None, token=None, parse_mode="HTML"):
            sent.append(text)
            return {"ok": True}

        monkeypatch.setattr(notifier, "SENDER", fake_send)
        return sent

    def test_reminder_for_14d_bucket(self, tmp_db, monkeypatch):
        user = _seed_user()
        opp_id = self._seed_deadline("2099-01-21")
        self._freeze_days_left(monkeypatch, date(2099, 1, 11))
        sent = self._send(monkeypatch)
        assert notifier.send_deadline_reminders(user) == 1
        assert len(sent) == 1
        assert "Deadline in 10 days" in sent[0]
        conn = db.get_connection()
        row = conn.execute("SELECT notified_14d FROM deadlines WHERE opportunity_id = ?", (opp_id,)).fetchone()
        conn.close()
        assert row["notified_14d"] == 1

    def test_each_bucket_fires_once(self, tmp_db, monkeypatch):
        user = _seed_user()
        opp_id = self._seed_deadline("2099-02-05")
        self._freeze_days_left(monkeypatch, date(2099, 1, 10))
        self._send(monkeypatch)
        assert notifier.send_deadline_reminders(user) == 1
        assert notifier.send_deadline_reminders(user) == 0
        conn = db.get_connection()
        row = conn.execute("SELECT notified_30d FROM deadlines WHERE opportunity_id = ?", (opp_id,)).fetchone()
        conn.close()
        assert row["notified_30d"] == 1

    def test_expired_marked_and_skipped(self, tmp_db, monkeypatch):
        user = _seed_user()
        opp_id = self._seed_deadline("2020-01-01")
        self._send(monkeypatch)
        assert notifier.send_deadline_reminders(user) == 0
        conn = db.get_connection()
        row = conn.execute("SELECT expired FROM deadlines WHERE opportunity_id = ?", (opp_id,)).fetchone()
        conn.close()
        assert row["expired"] == 1

    def test_not_eligible_skipped(self, tmp_db, monkeypatch):
        user = _seed_user()
        opp_id = self._seed_deadline("2099-01-01", eligibility="not_eligible")
        self._freeze_days_left(monkeypatch, date(2099, 1, 11))
        sent = self._send(monkeypatch)
        assert notifier.send_deadline_reminders(user) == 0
        assert sent == []

    def test_duplicate_opportunity_skipped(self, tmp_db, monkeypatch):
        user = _seed_user()
        original = self._seed_deadline("2099-01-21")
        dup = self._seed_deadline("2099-01-21", title="Scheme X (duplicate)")
        conn = db.get_connection()
        conn.execute("UPDATE opportunities SET duplicate_of = ? WHERE id = ?", (original, dup))
        conn.commit()
        conn.close()
        self._freeze_days_left(monkeypatch, date(2099, 1, 11))
        sent = self._send(monkeypatch)
        assert notifier.send_deadline_reminders(user) == 1
        assert len(sent) == 1