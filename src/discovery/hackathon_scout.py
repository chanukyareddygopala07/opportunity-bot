"""Hackathon Scout — discovers hackathons through the common adapter layer.

Pipeline per source (identical guarantees to the other scouts):
  adapter fetch -> role-free ingestion -> dedupe upsert -> deadline store ->
  deterministic scoring -> link verification -> discovery_runs bookkeeping.

Every emitted opportunity is type="hackathon"; mode is expressed via the
existing remote/hybrid flags; prizes land in funding; themes and team size
are appended to the requirements list so they surface on detail pages.
"""
import logging
import sys
import time

from src import db
from src import dedupe, sources as registry, verification
from src.discovery import hackathon_sources
from src.scoring import score_for_opportunity

logger = logging.getLogger(__name__)


def entry_to_opportunity(entry, source):
    title = (entry.get("title") or "").strip()
    url = entry.get("url")
    if not title or not url:
        return None
    if not str(url).startswith(("http://", "https://")):
        return None

    requirements = []
    if entry.get("team_size"):
        requirements.append(f"Team size: {entry['team_size']}")
    for theme in entry.get("themes") or []:
        if theme:
            requirements.append(f"Theme: {theme}")

    description = entry.get("description") or ""
    if entry.get("prize"):
        # funding is the existing display field for prize pools.
        pass

    return {
        "title": title[:200],
        "organization": entry.get("organization")
                        or source.get("organization") or "Unknown",
        "type": "hackathon",
        "category": "hackathon",
        "description": (description or f"{title} — via {source['name']}.")[:1000],
        "location": entry.get("location") or source.get("country_hint"),
        "remote": bool(entry.get("remote")),
        "hybrid": False,
        "deadline": entry.get("deadline"),
        "start_date": entry.get("event_start"),
        "end_date": entry.get("event_end"),
        "application_url": url,
        "official_url": url,
        "source_url": source.get("url"),
        "source_type": source.get("type", "official_program"),
        "funding": (f"Prize pool {entry['prize']}" if entry.get("prize") else None),
        "requirements": requirements,
    }


def scout_source(source, run_id=None):
    run_id = run_id or __import__("uuid").uuid4().hex[:8]
    name = source.get("name") or source.get("url")
    started = db.now_iso()
    stats = dict(run_id=run_id, scout="hackathon_scout",
                 source_id=source.get("id"), source_name=name,
                 source_url=source.get("url"), method=source.get("method"),
                 crawler="hackathon_adapter",
                 raw_items=0, role_gate=0, location_gate=0, pattern_gate=0,
                 extracted=0, stored_new=0, duplicates=0, eligible=0,
                 likely_eligible=0, unclear=0, not_eligible=0, published=0,
                 extraction_errors=0, retries=0, http_status=None,
                 response_ms=None, error=None, started_at=started,
                 finished_at=None)
    t0 = time.monotonic()

    try:
        entries = hackathon_sources.fetch_hackathons(source)
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        stats.update(error=err, finished_at=db.now_iso())
        registry.mark_failure(source["id"], err)
        db.record_discovery_run(**stats)
        db.log_error(name, type(exc).__name__, str(exc))
        logger.warning("hackathon source failed: %s (%s)", name, exc)
        return 0, 0

    stats["raw_items"] = len(entries)
    matched = 0
    for entry in entries:
        opportunity = entry_to_opportunity(entry, source)
        if opportunity is None:
            stats["extraction_errors"] += 1
            continue
        stats["extracted"] += 1
        try:
            opportunity_id = db.upsert_opportunity(opportunity)
            if opportunity.get("deadline"):
                db.upsert_deadline(opportunity_id, opportunity["deadline"])
            if dedupe.mark_if_duplicate(opportunity_id):
                stats["duplicates"] += 1
            else:
                stored = db.get_opportunity(opportunity_id)
                if stored and stored.get("first_seen") == stored.get("last_seen"):
                    stats["stored_new"] += 1
                    verification.verify_opportunity(opportunity_id)
            score_for_opportunity(opportunity_id)
            status = (db.get_opportunity(opportunity_id) or {}).get(
                "eligibility_status")
            if status in ("eligible", "likely_eligible"):
                stats[status] += 1
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
    stats.update(finished_at=db.now_iso(),
                 response_ms=int((time.monotonic() - t0) * 1000))
    db.record_discovery_run(**stats)
    logger.info("%s: raw=%d extracted=%d new=%d dup=%d",
                name, stats["raw_items"], stats["extracted"],
                stats["stored_new"], stats["duplicates"])
    return len(entries), matched


def run(category="hackathon", sources_file=None, run_id=None):
    db.init_db()
    sources = registry.load_config(sources_file) if sources_file else None
    registry.sync_sources(sources)
    total = 0
    for source in registry.list_enabled_sources(category):
        _, matched = scout_source(source, run_id=run_id)
        total += matched
    return total


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    count = run()
    print(f"hackathon scout finished: {count} new opportunities")
    sys.exit(0)
