"""Phase 7 — Internship Scout (Agent 2) with Phase 18 discovery improvements.

Discovers student-program roles from official public ATS APIs (Greenhouse/Ashby/
JSON) plus RSS/HTML sources. Phase 18 changes:

- role gate is configurable per source (`role_patterns`); default matches
  student-program titles broadly (intern, graduate, university, scholar,
  apprentice, trainee, fresher, summer, research assistant, new grad, campus,
  co-op) instead of only the word "intern"
- location filter is per source (`location_filter`: "india_remote" (default)
  or "any" — "any" stores foreign-onsite roles for review as unclear)
- every stage is counted into discovery_runs + filtering_decisions
- DEBUG_DISCOVERY / SAVE_REJECTED / SAVE_RAW_RESPONSES dump raw responses and
  rejected candidates to data/debug/ for analysis

Run manually:   python -m src.discovery.internship_scout
"""
import hashlib
import logging
import os
import re
import sys
import time
import uuid
from pathlib import Path

from src import db, dedupe, schema
from src import sources as registry
from src.discovery import entries, router
from src.scoring import score_for_opportunity
from src.verification import verify_opportunity

logger = logging.getLogger(__name__)

DEFAULT_ROLE_PATTERNS = (
    "intern", "graduate", "university", "scholar", "apprentice", "trainee",
    "fresher", "summer", "research assistant", "new grad",
)

INDIA_LOCATION_PATTERNS = [
    "india", "remote", "anywhere",
    "bengaluru", "bangalore", "hyderabad", "mumbai", "delhi", "chennai",
    "pune", "gurgaon", "gurugram", "noida", "kolkata",
]

DEBUG_DIR = Path(os.environ.get("OPP_CONFIG_DIR", Path(__file__).resolve().parent.parent / "config")).parent / "data" / "debug"


def _debug_enabled():
    return os.environ.get("DEBUG_DISCOVERY", "").strip().lower() in ("1", "true", "yes", "y")


def _save_rejected():
    return os.environ.get("SAVE_REJECTED", "").strip().lower() in ("1", "true", "yes", "y")


def _save_raw():
    return os.environ.get("SAVE_RAW_RESPONSES", "").strip().lower() in ("1", "true", "yes", "y")


def _dump(kind, run_id, name, payload):
    if not _debug_enabled():
        return None
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    import json
    path = DEBUG_DIR / f"{run_id}_{kind}_{re.sub(r'[^a-z0-9]+', '_', name.lower())[:40]}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return str(path)


def _matches(text, patterns):
    if not patterns:
        return False
    lower = text.lower()
    return any(p.lower() in lower for p in patterns)


def _role_matches(entry, patterns):
    """Word-boundary match so "intern" hits "intern", "interns",
    "internship", "internships" but not "International". Common suffixes
    (s, ship, ing, ies) are allowed after the pattern; multi-word patterns
    (e.g. "research assistant") match as phrases."""
    parts = [
        entry.get("title"),
        entry.get("employment_type"),
        entry.get("department"),
    ]
    text = " ".join(
        str(part) for part in parts if part not in (None, "")
    ).lower()
    return any(
        re.search(rf"\b{re.escape(pattern.lower())}(?:s|ship|ing|ies)?\b", text)
        for pattern in (patterns or DEFAULT_ROLE_PATTERNS)
    )


def classify_category(title, department):
    text = f"{title or ''} {department or ''}".lower()
    if any(key in text for key in ("quant", "trader", "trading", "desk")):
        return "quant"
    if any(key in text for key in ("ml", "machine learning", " ai", "llm", "data sci")):
        return "ai_ml"
    if "research" in text:
        return "research"
    if any(key in text for key in ("security", "cryptograph")):
        return "security"
    if any(key in text for key in ("data", "analyst", "analytics")):
        return "data_science"
    if any(key in text for key in ("finance", "fintech", "bank")):
        return "finance"
    return "software"


def entry_to_opportunity(entry, source):
    title = entry.get("title")
    url = entry.get("url")
    if not title or not url:
        return None
    trust = source.get("trust_score") or 0
    opportunity = {
        "title": title,
        "organization": source.get("organization"),
        "description": entry.get("description"),
        "application_url": url,
        "source_url": url,
        "source_type": source.get("type"),
        "type": "internship",
        "category": classify_category(title, entry.get("department")),
        "location": entry.get("location"),
        "listed_at": entry.get("published") or entry.get("posted_date"),
        "remote": entry.get("remote", False),
        "hybrid": entry.get("hybrid", False),
        "organization_trust_score": trust,
        "verification_status": "official" if trust >= 90 else "pending",
        "eligibility_status": "unknown",
    }
    return schema.normalize_opportunity(entries.enrich(opportunity, entry))


def _link_source(opportunity_id, source_id):
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO opportunity_sources (opportunity_id, source_id, seen_at) "
            "VALUES (?, ?, ?)",
            (opportunity_id, source_id, db.now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def _passes_location_filter(entry, source, patterns=None):
    method = source.get("method", "rss")
    if method not in entries.ATS_METHODS:
        return True
    filter_mode = source.get("location_filter") or "india_remote"
    if filter_mode == "any":
        return True
    patterns = patterns or source.get("location_patterns") or INDIA_LOCATION_PATTERNS
    location = entry.get("location") or ""
    if entry.get("remote") and "remote" not in location.lower():
        location = f"{location} (remote)"
    return _matches(location, patterns)


def scout_source(source, run_id=None):
    run_id = run_id or str(uuid.uuid4())[:8]
    name = source.get("name") or source.get("url")
    started = db.now_iso()
    stats = dict(run_id=run_id, scout="internship_scout", source_id=source.get("id"),
                 source_name=name, source_url=source.get("url"), method=source.get("method"),
                 crawler=router.select_crawler(source),
                 raw_items=0, role_gate=0, location_gate=0, pattern_gate=0,
                 extracted=0, stored_new=0, duplicates=0, eligible=0,
                 likely_eligible=0, unclear=0, not_eligible=0, published=0,
                 extraction_errors=0, retries=0, http_status=None, response_ms=None,
                 error=None, started_at=started, finished_at=None)
    t0 = time.monotonic()

    try:
        entries_list = entries.fetch_entries(source)
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        stats.update(error=err, finished_at=db.now_iso())
        registry.mark_failure(source["id"], err)
        db.record_discovery_run(**stats)
        db.log_error(name, type(exc).__name__, str(exc))
        db.log_execution(run_id, "internship_scout", name, "failed", str(exc), started)
        logger.warning("source failed: %s (%s)", name, exc)
        return 0, 0

    stats["raw_items"] = len(entries_list)
    if _save_raw():
        _dump("raw", run_id, name, entries_list)
        db.record_raw_response(run_id, source.get("id"), name, source.get("url"),
                               None, 0, None, None)

    role_patterns = source.get("role_patterns") or list(DEFAULT_ROLE_PATTERNS)
    kept = []
    for entry in entries_list:
        if not _role_matches(entry, role_patterns):
            db.record_filtering_decision(run_id, source.get("id"), "role",
                                         entry.get("title"), source.get("organization"),
                                         entry.get("url"), "role gate")
            if _save_rejected():
                _dump("rejected_role", run_id, name, entry)
            continue
        stats["role_gate"] += 1
        if not _passes_location_filter(entry, source):
            db.record_filtering_decision(run_id, source.get("id"), "location",
                                         entry.get("title"), source.get("organization"),
                                         entry.get("url"), "location gate")
            if _save_rejected():
                _dump("rejected_location", run_id, name, entry)
            continue
        stats["location_gate"] += 1
        method = source.get("method", "rss")
        if method not in entries.ATS_METHODS:
            haystack = (entry.get("title") or "") + " " + (entry.get("description") or "")
            if source.get("include_patterns") and not _matches(haystack, source["include_patterns"]):
                db.record_filtering_decision(run_id, source.get("id"), "patterns",
                                             entry.get("title"), source.get("organization"),
                                             entry.get("url"), "include patterns")
                if _save_rejected():
                    _dump("rejected_patterns", run_id, name, entry)
                continue
            if source.get("exclude_patterns") and _matches(haystack, source["exclude_patterns"]):
                db.record_filtering_decision(run_id, source.get("id"), "patterns",
                                             entry.get("title"), source.get("organization"),
                                             entry.get("url"), "exclude patterns")
                if _save_rejected():
                    _dump("rejected_patterns", run_id, name, entry)
                continue
        stats["pattern_gate"] += 1
        kept.append(entry)

    for entry in kept:
        opportunity = entry_to_opportunity(entry, source)
        if opportunity is None:
            stats["extraction_errors"] += 1
            continue
        stats["extracted"] += 1
        try:
            opportunity_id = db.upsert_opportunity(opportunity)
            _link_source(opportunity_id, source["id"])
            if opportunity.get("deadline"):
                db.upsert_deadline(opportunity_id, opportunity["deadline"])
            if dedupe.mark_if_duplicate(opportunity_id):
                stats["duplicates"] += 1
            else:
                stored = db.get_opportunity(opportunity_id)
                if stored and stored.get("first_seen") == stored.get("last_seen"):
                    stats["stored_new"] += 1
            score_for_opportunity(opportunity_id)
            stored = db.get_opportunity(opportunity_id)
            if stored and stored.get("first_seen") == stored.get("last_seen"):
                verify_opportunity(opportunity_id)
            status = stored.get("eligibility_status") if stored else None
            if status == "eligible":
                stats["eligible"] += 1
                stats["published"] += 1
            elif status == "likely_eligible":
                stats["likely_eligible"] += 1
                stats["published"] += 1
            elif status == "not_eligible":
                stats["not_eligible"] += 1
            else:
                stats["unclear"] += 1
        except ValueError as exc:
            stats["extraction_errors"] += 1
            db.log_error(name, "ValueError", str(exc))

    registry.mark_success(source["id"])
    stats.update(finished_at=db.now_iso(), response_ms=int((time.monotonic() - t0) * 1000))
    db.record_discovery_run(**stats)
    db.log_execution(
        run_id, "internship_scout", name, "success",
        f"seen={stats['raw_items']} role={stats['role_gate']} "
        f"loc={stats['location_gate']} stored_new={stats['stored_new']} "
        f"dups={stats['duplicates']}", started,
    )
    logger.info("%s: raw=%d role=%d loc=%d new=%d dup=%d",
                name, stats["raw_items"], stats["role_gate"],
                stats["location_gate"], stats["stored_new"], stats["duplicates"])
    return stats["raw_items"], stats["stored_new"]


def run(category="internship", sources_file=None, run_id=None):
    db.init_db()
    sources = registry.load_config(sources_file) if sources_file else None
    registry.sync_sources(sources)
    total = 0
    for source in registry.list_enabled_sources(category):
        _, matched = scout_source(source, run_id=run_id)
        total += matched
    return total


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    count = run()
    print(f"internship scout finished: {count} new opportunities")
    sys.exit(0)