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
    from src import ai, maintenance
    from src.discovery import fellowship_scout, internship_scout
    from src.notifications import notifier

    run_id = str(uuid.uuid4())[:8]
    started = db.now_iso()
    fellowship_new = fellowship_scout.run(category="fellowship")
    internship_new = internship_scout.run(category="internship")
    notified = notifier.run()
    ai_assessed = ai.assess_new()
    maintenance_result = maintenance.run_maintenance()
    summary = {
        "fellowship_scout": fellowship_new,
        "internship_scout": internship_new,
        "notifications": notified,
        "ai_assessments": ai_assessed,
        "maintenance": maintenance_result,
        "discovery": discovery_summary(),
    }
    db.log_execution(
        run_id, "worker", "pipeline", "success", json.dumps(summary), started
    )
    print(json.dumps(summary))
    return summary


if __name__ == "__main__":
    run_pipeline()
    sys.exit(0)