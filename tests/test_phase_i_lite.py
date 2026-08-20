"""Phase I-lite: in-app notifications + recently viewed + UX states."""
import secrets
from datetime import datetime, timedelta, timezone

from src import db
from src.webapp import auth
from src.notifications import notifier


def _login(client, user_id):
    token = secrets.token_urlsafe(32)
    db.create_session(
        user_id, token,
        (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    )
    client.set_cookie(auth.SESSION_COOKIE, token)


def _opp(**overrides):
    data = {
        "title": "Test Internship", "organization": "TestOrg",
        "type": "internship", "application_url": "https://t.example/apply",
        "verification_status": "verified", "match_score": 80,
    }
    data.update(overrides)
    return db.upsert_opportunity(data)


class TestInAppNotifications:
    def test_new_opportunity_notifies_matching_users(self, tmp_db):
        uid = db.create_user("u1", password_hash="x", profile={})
        _opp(eligibility_status="eligible")
        sent = notifier.send_new_opportunities_in_app()
        assert sent == 1
        notes = db.list_user_notifications(uid)
        assert len(notes) == 1
        assert notes[0]["kind"] == "new_opportunity"
        assert notes[0]["delivered"] == 0

    def test_does_not_notify_ineligible_or_unverified(self, tmp_db):
        uid = db.create_user("u1", password_hash="x", profile={})
        _opp(eligibility_status="not_eligible")
        _opp(verification_status="unverified", eligibility_status="eligible")
        assert notifier.send_new_opportunities_in_app() == 0
        assert db.list_user_notifications(uid) == []

    def test_each_opportunity_alerts_each_user_once(self, tmp_db):
        uid = db.create_user("u1", password_hash="x", profile={})
        _opp(eligibility_status="eligible")
        assert notifier.send_new_opportunities_in_app() == 1
        assert notifier.send_new_opportunities_in_app() == 0

    def test_deadline_reminders_only_for_bookmarked(self, tmp_db):
        from datetime import date, timedelta
        soon = (date.today() + timedelta(days=10)).isoformat()
        later = (date.today() + timedelta(days=25)).isoformat()
        uid = db.create_user("u1", password_hash="x", profile={})
        opp_id = _opp(eligibility_status="eligible", deadline=soon)
        db.upsert_deadline(opp_id, soon)
        other_id = _opp(
            title="Other Opp", organization="Other",
            eligibility_status="eligible", deadline=later,
        )
        db.upsert_deadline(other_id, later)
        db.add_bookmark(uid, other_id)
        sent = notifier.send_deadline_reminders_in_app()
        assert sent == 1
        notes = db.list_user_notifications(uid)
        assert len(notes) == 1
        assert notes[0]["kind"] == "deadline_reminder"
        assert notes[0]["opportunity_id"] == other_id

    def test_mark_read_and_count(self, tmp_db):
        uid = db.create_user("u1", password_hash="x", profile={})
        _opp(eligibility_status="eligible")
        notifier.send_new_opportunities_in_app()
        assert db.unread_notification_count(uid) == 1
        db.mark_user_notifications_read(uid)
        assert db.unread_notification_count(uid) == 0


class TestRecentlyViewed:
    def test_record_and_list(self, tmp_db):
        uid = db.create_user("u1", password_hash="x", profile={})
        opp_id = _opp()
        db.record_view(uid, opp_id)
        seen = db.recently_viewed(uid)
        assert len(seen) == 1
        assert seen[0]["id"] == opp_id

    def test_view_updates_timestamp_not_duplicates(self, tmp_db):
        uid = db.create_user("u1", password_hash="x", profile={})
        opp_id = _opp()
        db.record_view(uid, opp_id)
        db.record_view(uid, opp_id)
        assert len(db.recently_viewed(uid)) == 1


class TestWeb:
    def test_notifications_page_requires_login(self, client):
        assert client.get("/notifications").status_code == 302

    def test_notifications_page_empty_state(self, client, app):
        with app.app_context():
            uid = db.create_user("u1", password_hash="x", profile={})
        _login(client, uid)
        resp = client.get("/notifications")
        assert resp.status_code == 200
        assert b"No notifications yet" in resp.data

    def test_notifications_mark_all_read(self, client, app):
        with app.app_context():
            uid = db.create_user("u1", password_hash="x", profile={})
            _opp(eligibility_status="eligible")
            notifier.send_new_opportunities_in_app()
        _login(client, uid)
        resp = client.post("/notifications")
        assert resp.status_code == 302
        assert db.unread_notification_count(uid) == 0

    def test_detail_records_view(self, client, app):
        with app.app_context():
            uid = db.create_user("u1", password_hash="x", profile={})
            opp_id = _opp()
        _login(client, uid)
        assert client.get(f"/o/{opp_id}").status_code == 200
        assert [o["id"] for o in db.recently_viewed(uid)] == [opp_id]

    def test_recently_viewed_page(self, client, app):
        with app.app_context():
            uid = db.create_user("u1", password_hash="x", profile={})
            opp_id = _opp()
            db.record_view(uid, opp_id)
        _login(client, uid)
        resp = client.get("/recently-viewed")
        assert resp.status_code == 200
        assert b"Your recently viewed" in resp.data

    def test_unread_badge_in_nav(self, client, app):
        with app.app_context():
            uid = db.create_user("u1", password_hash="x", profile={})
            _opp(eligibility_status="eligible")
            notifier.send_new_opportunities_in_app()
        _login(client, uid)
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"has-badge" in resp.data

    def test_skip_link_present(self, client):
        assert b"skip-link" in client.get("/").data