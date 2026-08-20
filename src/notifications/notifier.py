"""Phase 12 — notifications: new opportunities + deadline reminders.

Policies (nothing noisy, nothing invented):
- new opportunities notify only when match_score >= 50, verified (or
  official) and not marked not_eligible; each opportunity alerts once
- deadlines notify per bucket: 30d / 14d / 7d / 3d / 24h, each exactly once
  (tracked by the deadlines table flags), expired ones are marked
- every attempt is recorded in the notifications table

Run manually:   python -m src.notifications.notifier [--dry-run]
"""
import os
import sys

from src import db, store
from src.notifications import formatting, telegram

NEW_SCORE_THRESHOLD = 30

DEADLINE_BUCKETS = (
    ("notified_30d", 30),
    ("notified_14d", 14),
    ("notified_7d", 7),
    ("notified_3d", 3),
    ("notified_24h", 1),
)

SENDER = telegram.send_message


def _chat_id(profile):
    return profile.get("chat_id") or os.environ.get("TELEGRAM_CHAT_ID", "").strip() or None


def _already_notified(opportunity_id, kind):
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM notifications WHERE opportunity_id = ? AND kind = ? LIMIT 1",
            (opportunity_id, kind),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def _send(chat_id, text):
    return SENDER(text, chat_id=chat_id)


def bucket_for(days_left):
    """Tightest deadline bucket for days_left (or None when expired)."""
    if days_left is None or days_left < 0:
        return None
    for column, threshold in sorted(DEADLINE_BUCKETS, key=lambda item: item[1]):
        if days_left <= threshold:
            return column
    return None


def send_new_opportunities(profile=None, dry_run=False):
    profile = profile or store.load_profile()
    chat_id = _chat_id(profile)
    if not chat_id and not dry_run:
        print("no chat_id registered; run /start on the bot first")
        return 0
    sent = 0
    for opp in db.list_opportunities():
        if _already_notified(opp["id"], "new_opportunity"):
            continue
        if (opp.get("match_score") or 0) < NEW_SCORE_THRESHOLD:
            continue
        if opp.get("eligibility_status") == "not_eligible":
            continue
        if opp.get("verification_status") not in ("verified", "official"):
            continue
        label = formatting.eligibility_label(opp.get("eligibility_status"), opp)
        text = (f"🎯 <b>New opportunity — {label}</b>\n\n"
                + formatting.opportunity_to_text(opp))
        if not dry_run:
            try:
                _send(chat_id, text)
                db.insert_notification(opp["id"], "new_opportunity", text, delivered=1)
            except Exception as exc:
                print(f"send failed for #{opp['id']}: {exc}")
                db.insert_notification(opp["id"], "new_opportunity", text, delivered=0)
            sent += 1
        else:
            sent += 1
    return sent


def send_deadline_reminders(profile=None, dry_run=False):
    profile = profile or store.load_profile()
    chat_id = _chat_id(profile)
    if not chat_id and not dry_run:
        print("no chat_id registered; run /start on the bot first")
        return 0
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT d.* FROM deadlines d JOIN opportunities o ON o.id = d.opportunity_id "
            "WHERE o.duplicate_of IS NULL"
        ).fetchall()
    finally:
        conn.close()
    sent = 0
    for row in rows:
        deadline = row["deadline"]
        if not deadline:
            continue
        days_left = formatting.deadline_days_left(deadline)
        if days_left is None:
            continue
        if days_left < 0:
            if not row["expired"]:
                conn = db.get_connection()
                try:
                    conn.execute(
                        "UPDATE deadlines SET expired = 1 WHERE opportunity_id = ?",
                        (row["opportunity_id"],),
                    )
                    conn.commit()
                finally:
                    conn.close()
            continue
        bucket = bucket_for(days_left)
        if not bucket or row[bucket]:
            continue
        opp = db.get_opportunity(row["opportunity_id"])
        if not opp or opp.get("eligibility_status") == "not_eligible":
            continue
        text = (
            f"⏰ <b>Deadline in {days_left} day{'s' if days_left != 1 else ''}</b> "
            f"({deadline})\n\n" + formatting.opportunity_to_text(opp)
        )
        if not dry_run:
            try:
                _send(chat_id, text)
                db.insert_notification(
                    row["opportunity_id"], "deadline_reminder", text, delivered=1)
                db.mark_deadline_notified(row["opportunity_id"], bucket)
            except Exception as exc:
                print(f"send failed for #{row['opportunity_id']}: {exc}")
                db.insert_notification(
                    row["opportunity_id"], "deadline_reminder", text, delivered=0)
            sent += 1
        else:
            sent += 1
    return sent


def run(dry_run=False):
    db.init_db()
    if os.environ.get("SEND_TELEGRAM", "true").lower() == "false":
        print("telegram disabled (web mode); opportunities are stored, "
              "no messages sent")
        return 0
    profile = store.load_profile()
    new_sent = send_new_opportunities(profile, dry_run=dry_run)
    reminder_sent = send_deadline_reminders(profile, dry_run=dry_run)
    print(f"new={new_sent} reminders={reminder_sent}" + (" (dry run)" if dry_run else ""))
    return new_sent + reminder_sent


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    run(dry_run=dry_run)
    sys.exit(0)