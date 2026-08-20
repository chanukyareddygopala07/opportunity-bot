"""Phase 6 — Fellowship Scout.

Discovers fellowship/scholarship/research opportunities from official sources
in the registry, normalizes them through the Phase 5 schema, deduplicates via
the unique dedup_key, and stores them in the database.

Run manually:   python -m src.discovery.fellowship_scout
Later called by n8n (Phase 14 scheduling).
"""
import logging
import sys
import uuid

from src import db, dedupe, schema
from src import sources as registry
from src.discovery import entries, fetcher
from src.scoring import score_for_opportunity
from src.verification import verify_opportunity

logger = logging.getLogger(__name__)


def _matches(text, patterns):
    if not patterns:
        return False
    lower = text.lower()
    return any(pattern.lower() in lower for pattern in patterns)


def entry_to_opportunity(entry, source):
    title = entry.get("title")
    url = entry.get("url") or entry.get("link")
    if not title or not url:
        return None
    trust = source.get("trust_score") or 0
    source_category = source.get("category") or "fellowship"
    opp_type = {
        "fellowship": "fellowship",
        "scholarship": "scholarship",
        "research_program": "research_program",
        "summer_program": "summer_program",
    }.get(source_category, "fellowship")
    opportunity = {
        "title": title,
        "organization": source.get("organization"),
        "description": entry.get("description"),
        "application_url": url,
        "source_url": url,
        "source_type": source.get("type"),
        "type": opp_type,
        "category": source.get("category") or "other",
        "listed_at": entry.get("published"),
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


def scout_source(source):
    run_id = str(uuid.uuid4())[:8]
    name = source.get("name") or source.get("url")
    started = db.now_iso()
    stats = dict(run_id=run_id, scout="fellowship_scout", source_id=source.get("id"),
                 source_name=name, source_url=source.get("url"), method=source.get("method"),
                 raw_items=0, role_gate=0, location_gate=0, pattern_gate=0,
                 extracted=0, stored_new=0, duplicates=0, eligible=0,
                 likely_eligible=0, unclear=0, not_eligible=0, published=0,
                 extraction_errors=0, retries=0, http_status=None, response_ms=None,
                 error=None, started_at=started, finished_at=None)
    try:
        entries_list = entries.fetch_entries(source)
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        stats.update(error=err, finished_at=db.now_iso())
        registry.mark_failure(source["id"], err)
        db.record_discovery_run(**stats)
        db.log_error(name, type(exc).__name__, str(exc))
        db.log_execution(run_id, "fellowship_scout", name, "failed", str(exc), started)
        logger.warning("source failed: %s (%s)", name, exc)
        return 0, 0

    stats["raw_items"] = len(entries_list)
    matched = 0
    duplicates = 0
    for entry in entries_list:
        title = entry.get("title") or ""
        haystack = title + " " + (entry.get("description") or "")
        if source.get("include_patterns") and not _matches(haystack, source["include_patterns"]):
            db.record_filtering_decision(run_id, source.get("id"), "patterns",
                                         title, source.get("organization"),
                                         entry.get("url") or entry.get("link"),
                                         "include patterns")
            continue
        if source.get("exclude_patterns") and _matches(haystack, source["exclude_patterns"]):
            db.record_filtering_decision(run_id, source.get("id"), "patterns",
                                         title, source.get("organization"),
                                         entry.get("url") or entry.get("link"),
                                         "exclude patterns")
            continue
        stats["pattern_gate"] += 1
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
                duplicates += 1
                stats["duplicates"] += 1
            score_for_opportunity(opportunity_id)
            stored = db.get_opportunity(opportunity_id)
            if stored and stored.get("first_seen") == stored.get("last_seen"):
                stats["stored_new"] += 1
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
            matched += 1
        except ValueError as exc:
            stats["extraction_errors"] += 1
            db.log_error(name, "ValueError", str(exc))

    registry.mark_success(source["id"])
    stats.update(finished_at=db.now_iso())
    db.record_discovery_run(**stats)
    db.log_execution(
        run_id, "fellowship_scout", name, "success",
        f"seen={len(entries_list)} matched={matched} duplicates={duplicates}", started,
    )
    logger.info("%s: seen=%d matched=%d", name, len(entries_list), matched)
    return len(entries_list), matched


def run(category="fellowship", sources_file=None):
    db.init_db()
    sources = registry.load_config(sources_file) if sources_file else None
    registry.sync_sources(sources)
    total = 0
    for source in registry.list_enabled_sources(category):
        _, matched = scout_source(source)
        total += matched
    return total


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    count = run()
    print(f"fellowship scout finished: {count} opportunities")
    sys.exit(0)