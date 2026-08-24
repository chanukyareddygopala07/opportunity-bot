"""Detail-page enrichment — the accuracy pass for published opportunities.

Why: listing pages are thin (Internshala cards carry no dates, Devpost list
API has no eligibility text). This pass reads each opportunity's own detail
page through Jina Reader, re-extracts facts with the deterministic
extractor, and reconciles against stored values:

    stored missing + page found   -> FILL      (change recorded)
    stored value == page value    -> CONFIRM   (verification boosted)
    stored value != page value    -> CONFLICT  (flagged, never overwritten)

Conflicts go to `opportunity_changes` as `<field>_conflict` rows and keep
the record out of the verified state until resolved. Nothing is ever
silently overwritten — a webpage cannot silently rewrite our database.
"""
import logging
import time

from src import db, deadlines, verification
from src.discovery import jina
from src.extraction.extractor import find_deadline
from src.scoring import score_for_opportunity

logger = logging.getLogger(__name__)

MAX_PAGES_PER_RUN = 15
MAX_TEXT_CHARS = 40_000


def _pick_candidates(limit):
    """Published records that gain most from a detail-page check:
    missing deadline first (oldest last_seen), then unverified ones."""
    conn = db.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT * FROM opportunities
            WHERE duplicate_of IS NULL
              AND status IN ('new', 'seen')
              AND (deadline IS NULL OR verification_status NOT IN ('verified', 'official'))
              AND (application_url LIKE 'http%' OR official_url LIKE 'http%')
            ORDER BY (deadline IS NULL) DESC, last_seen ASC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _detail_url(opp):
    return opp.get("application_url") or opp.get("official_url")


def reconcile(opp, page_text):
    """Compare stored record with freshly extracted page facts.

    Returns dict(action=fill|confirm|conflict|nothing, fields=[...]).
    """
    actions = {}
    found_deadline = find_deadline(page_text[:MAX_TEXT_CHARS])
    stored_deadline = opp.get("deadline")
    outcome = {"action": "nothing", "fields": []}

    if found_deadline and stored_deadline is None:
        db.update_opportunity(opp["id"], deadline=found_deadline,
                              deadline_status=deadlines.status(
                                  {"deadline": found_deadline}))
        db.record_opportunity_change(
            opp["id"], "deadline_filled", None, str(found_deadline))
        actions["deadline"] = ("filled", None, found_deadline)
        outcome["action"] = "fill"
        outcome["fields"].append("deadline")
    elif found_deadline and str(found_deadline)[:10] == str(stored_deadline)[:10]:
        if opp.get("verification_status") not in ("verified", "official"):
            # The source itself re-states the deadline: honest confirmation.
            trust_ok = (opp.get("organization_trust_score") or 0) >= 90
            new_status = "verified" if trust_ok else opp.get("verification_status")
            if new_status and new_status != opp.get("verification_status"):
                db.update_opportunity(opp["id"], verification_status=new_status)
                db.record_verification(opp["id"], new_status, "confirmed",
                                       "deadline re-confirmed on detail page")
                actions["deadline"] = ("confirmed", stored_deadline,
                                       found_deadline)
                outcome["action"] = "confirm"
                outcome["fields"].append("verification_status")
        else:
            actions["deadline"] = ("confirmed", stored_deadline, found_deadline)
            outcome["fields"].append("deadline")
    elif found_deadline and stored_deadline not in (None, ""):
        db.record_opportunity_change(
            opp["id"], "deadline_conflict",
            str(stored_deadline), str(found_deadline))
        actions["deadline"] = ("conflict", stored_deadline, found_deadline)
        outcome["action"] = "conflict"

    if outcome["fields"] or actions:
        outcome["details"] = actions
    return outcome


def enrich_one(opp):
    """Enrich a single opportunity via its detail page."""
    url = _detail_url(opp)
    if not url:
        return {"id": opp["id"], "action": "skipped_no_url"}
    started = time.monotonic()
    text = jina.read(url)
    duration_ms = int((time.monotonic() - started) * 1000)
    try:
        db.record_agent_metric("enrichment", "pages_read_total", 1)
        db.record_agent_metric("enrichment", "read_duration_ms", duration_ms)
    except Exception:
        pass
    if not text:
        return {"id": opp["id"], "action": "unreadable"}
    outcome = reconcile(opp, text)
    if outcome["action"] == "fill":
        score_for_opportunity(opp["id"])
    outcome["id"] = opp["id"]
    return outcome


def run_enrichment(limit=MAX_PAGES_PER_RUN):
    """Run one enrichment pass; returns an honest summary for run logs."""
    candidates = _pick_candidates(limit)
    summary = {"candidates": len(candidates), "filled": 0, "confirmed": 0,
               "conflicts": 0, "unreadable": 0, "no_change": 0}
    conflicts = []
    for opp in candidates:
        try:
            outcome = enrich_one(opp)
        except Exception as exc:
            logger.warning("enrichment failed for %s: %s",
                           opp.get("id"), exc)
            summary["unreadable"] += 1
            continue
        action = outcome.get("action")
        if action == "fill":
            summary["filled"] += 1
        elif action == "confirm":
            summary["confirmed"] += 1
        elif action == "conflict":
            summary["conflicts"] += 1
            conflicts.append({"id": opp["id"], "title": opp.get("title")})
        elif action == "unreadable":
            summary["unreadable"] += 1
        else:
            summary["no_change"] += 1
    summary["conflicting_records"] = conflicts
    return summary


# Re-exported for callers that verify links after enrichment.
verify_due = verification.verify_due
