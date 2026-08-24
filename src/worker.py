"""Phase 13 — the scheduled pipeline entry point.

Runs discovery (both scouts), then notifications; used by the n8n webhook
scheduler and by `python -m src.worker`.

Phase 18: emits a discovery summary with per-source stage counts from
discovery_runs so pipeline losses are visible without manual debugging.
"""
import json
import sys
import uuid

from src import db


def discovery_summary(limit=200):
    rows = db.list_recent_discovery_runs(limit=limit)
    if not rows:
        return {}
    summary = {"sources": len(rows), "totals": {}, "failed": [], "top_rejections": []}
    totals = summary["totals"]
    for r in rows:
        for key in ("raw_items", "role_gate", "location_gate", "pattern_gate",
                    "extracted", "stored_new", "duplicates", "eligible",
                    "likely_eligible", "unclear", "not_eligible", "published",
                    "extraction_errors"):
            totals[key] = totals.get(key, 0) + (r.get(key) or 0)
        if r.get("error"):
            summary["failed"].append({
                "source": r.get("source_name"), "error": r["error"],
            })
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT stage, reason, COUNT(*) AS n FROM filtering_decisions "
            "GROUP BY stage, reason ORDER BY n DESC LIMIT 10"
        ).fetchall()
        summary["top_rejections"] = [dict(r) for r in rows]
    finally:
        conn.close()
    return summary


def run_pipeline():
    db.init_db()
    from src import ai, maintenance, queue as crawl_queue, verification
    from src.discovery import fellowship_scout, internship_scout
    from src.notifications import notifier

    # Full uuid; the 8-char display id is only for humans.
    run_id = str(uuid.uuid4())
    started = db.now_iso()
    summary = {}
    try:
        queued = crawl_queue.enqueue_from_sources(run_id)
        fellowship_new = fellowship_scout.run(
            category="fellowship", run_id=run_id)
        internship_new = internship_scout.run(
            category="internship", run_id=run_id)
        settled = crawl_queue.settle(run_id)
        verified = verification.verify_due(limit=20)
        notified = notifier.run()
        ai_assessed = ai.assess_new()
        maintenance_result = maintenance.run_maintenance()
        summary = {
            "run_id": run_id,
            "fellowship_scout": fellowship_new,
            "internship_scout": internship_new,
            "notifications": notified,
            "ai_assessments": ai_assessed,
            "verification": verified,
            "crawl_queue": {"queued": queued, "settled": settled},
            "maintenance": maintenance_result,
            "discovery": discovery_summary(),
        }
        status, message = "success", json.dumps(summary)
    except Exception as exc:
        # A failed stage must never skip run logging.
        summary = {"run_id": run_id, "error": f"{type(exc).__name__}: {exc}"}
        status, message = "failed", json.dumps(summary)
    db.log_execution(run_id, "worker", "pipeline", status, message, started)
    print(json.dumps(summary))
    if status == "failed":
        raise RuntimeError(message) from None
    return summary


if __name__ == "__main__":
    run_pipeline()
    sys.exit(0)