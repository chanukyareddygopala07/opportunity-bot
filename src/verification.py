"""Phase 11 — verification & trust (v2: official-source priority + scheduling).

A discovered opportunity only becomes "verified" when its application link
is live AND it comes from an official source (trust >= 90) or is
corroborated by multiple independent sources. Dead links and non-official
items stay unverified with a recorded reason. Nothing is ever marked
verified without a live check.

v2 changes:
- official_url is checked BEFORE the application URL (official > aggregator)
- every verified item gets a next_verification deadline, tighter when the
  application deadline is near (<=7d: 12h, <=30d: 24h, else weekly)
- verify_due() powers the pipeline so the queue drains every run

Run manually:   python -m src.verification
"""
import sys
from datetime import datetime, timedelta, timezone

from src import db, deadlines
from src.discovery import fetcher

CHECK_TIMEOUT = 10
CHECK_MAX_BYTES = 65536


def check_link(url):
    """Returns (status, message): live / dead / error.

    404/410 mean the page is really gone -> dead. 403/429 usually mean a bot
    wall, not closure: treating those as dead falsely killed live links, so
    they return "error" (status preserved, re-check scheduled).
    """
    try:
        data, final_url, _status = fetcher.fetch_bytes(
            url, timeout=CHECK_TIMEOUT, max_bytes=CHECK_MAX_BYTES, attempts=1
        )
        return "live", "link responds"
    except fetcher.FetchError as exc:
        if exc.code == 403 or exc.code == 429:
            return "error", f"HTTP {exc.code} (bot-blocked; not treated as dead)"
        if exc.code is not None and 400 <= exc.code < 600:
            return "dead", f"HTTP {exc.code}"
        return "error", str(exc)[:200]


def _source_count(opportunity_id):
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM opportunity_sources WHERE opportunity_id = ?",
            (opportunity_id,),
        ).fetchone()
        return row["n"]
    finally:
        conn.close()


def _check_url(opp):
    """Official source first, then the application destination, then the source."""
    return (
        opp.get("official_url")
        or opp.get("application_url")
        or opp.get("source_url")
    )


def schedule_next_verification(opp, status, now=None):
    """Tighter verification cadence as deadlines approach; weekly otherwise."""
    now = now or datetime.now(timezone.utc)
    days = deadlines.days_left(opp.get("deadline"))
    if days is not None and days <= 7:
        hours = 12
    elif days is not None and days <= 30:
        hours = 24
    elif status == "verified":
        hours = 7 * 24
    else:
        hours = 24
    next_at = (now + timedelta(hours=hours)).isoformat()
    db.update_opportunity(opp["id"], next_verification=next_at)
    return next_at


def verify_opportunity(opportunity_id):
    """Verifies one opportunity. Returns (status, message) or None."""
    opp = db.get_opportunity(opportunity_id)
    if not opp:
        return None
    url = _check_url(opp)
    if not url:
        db.record_verification(opportunity_id, "unverified", None, "no application url")
        db.update_opportunity(opportunity_id, verification_status="unverified")
        schedule_next_verification(opp, "unverified")
        return "unverified", "no application url"

    link_status, link_message = check_link(url)
    if link_status == "error":
        db.record_verification(opportunity_id, opp.get("verification_status") or "pending",
                               "error", link_message)
        schedule_next_verification(opp, opp.get("verification_status") or "pending")
        return opp.get("verification_status") or "pending", "link check failed"

    if link_status == "dead":
        db.record_verification(opportunity_id, "unverified", "dead", link_message)
        db.update_opportunity(opportunity_id, verification_status="unverified")
        schedule_next_verification(opp, "unverified")
        return "unverified", f"link dead ({link_message})"

    trust = opp.get("organization_trust_score") or 0
    official = trust >= 90 or opp.get("verification_status") == "official"
    corroborated = _source_count(opportunity_id) >= 2
    if official or corroborated:
        message = "link live"
        if corroborated:
            message += f"; corroborated by {_source_count(opportunity_id)} sources"
        db.record_verification(opportunity_id, "verified", "live", message)
        db.update_opportunity(opportunity_id, verification_status="verified")
        schedule_next_verification(opp, "verified")
        return "verified", message
    db.record_verification(opportunity_id, "unverified", "live",
                           "link live but source not official")
    db.update_opportunity(opportunity_id, verification_status="unverified")
    schedule_next_verification(opp, "unverified")
    return "unverified", "link live but source not official"


def verify_all(limit=None, only_pending=False):
    """Verifies opportunities; returns counts {status: n}."""
    items = db.list_opportunities(exclude_duplicates=False)
    counts = {}
    done = 0
    for opp in items:
        if only_pending and opp.get("verification_status") == "verified":
            continue
        status, message = verify_opportunity(opp["id"])
        counts[status] = counts.get(status, 0) + 1
        done += 1
        if limit and done >= limit:
            break
    return counts


def verify_due(limit=20):
    """Verifies items that are due (deadline-first), then schedules the next check."""
    counts = {}
    for opp in db.get_due_verifications(limit=limit):
        status, _message = verify_opportunity(opp["id"])
        counts[status] = counts.get(status, 0) + 1
    return counts


if __name__ == "__main__":
    db.init_db()
    counts = verify_all()
    print("verification summary:", dict(sorted(counts.items())))
    for opp in db.list_opportunities():
        if opp.get("verification_status") != "verified":
            print(f"  {opp.get('verification_status'):<12} {opp.get('title', '')[:60]}")
    sys.exit(0)