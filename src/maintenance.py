"""Phase 16 — periodic maintenance: expiry + retention.

Idempotent and conservative:
- opportunities with a passed deadline are marked status='expired'
- old execution_logs / system_errors (90 days) and notifications (180 days)
  are pruned
Run manually:  python -m src.maintenance
"""
import sys
from datetime import datetime, timedelta, timezone

from src import db


def run_maintenance():
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    conn = db.get_connection()
    try:
        cur = conn.execute(
            "UPDATE opportunities SET status = 'expired' "
            "WHERE status IN ('new', 'seen') AND deadline IS NOT NULL AND deadline < ?",
            (today,),
        )
        expired = cur.rowcount
        refreshed = db.refresh_deadline_and_trust(conn=conn)
        cutoff_90 = (now - timedelta(days=90)).isoformat()
        cur = conn.execute("DELETE FROM execution_logs WHERE started_at < ?", (cutoff_90,))
        pruned_logs = cur.rowcount
        cur = conn.execute("DELETE FROM system_errors WHERE occurred_at < ?", (cutoff_90,))
        pruned_errors = cur.rowcount
        cutoff_180 = (now - timedelta(days=180)).isoformat()
        cur = conn.execute("DELETE FROM notifications WHERE sent_at < ?", (cutoff_180,))
        pruned_notifications = cur.rowcount
        conn.commit()
        return {
            "expired": expired,
            "refreshed": refreshed,
            "pruned_logs": pruned_logs,
            "pruned_errors": pruned_errors,
            "pruned_notifications": pruned_notifications,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    db.init_db()
    result = run_maintenance()
    print(result)
    sys.exit(0)