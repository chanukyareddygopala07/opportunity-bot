"""Crawl job queue — plans and settles the crawl work for a pipeline run.

The queue is a first-class record of what we intend to crawl and with which
crawler (router decision). Scouts execute the work; settle() copies the real
counts from discovery_runs back onto the jobs so the queue stays honest.
"""
import logging

from src import db, sources as registry
from src.discovery import router

logger = logging.getLogger(__name__)


def enqueue_from_sources(run_id):
    """Queue one job per enabled source for this run (skips if already queued)."""
    registry.sync_sources()
    pending = db.crawl_queue_stats().get("QUEUED", 0)
    if pending:
        logger.info("queue: %d jobs already queued, skipping enqueue", pending)
        return 0
    counts = db.deadline_days_active()
    queued = 0
    for source in registry.list_enabled_sources():
        if not source.get("url"):
            continue
        crawler = router.select_crawler(source)
        if crawler == router.RESPECT_ROBOTS:
            continue
        priority = router.priority_for_source(source, recent_deadlines=counts)
        db.enqueue_crawl_job(
            run_id, source.get("id"), source.get("name"),
            source.get("url"), crawler, priority,
        )
        queued += 1
    return queued


def settle(run_id):
    """Copy real run counts onto this run's jobs and mark them completed."""
    per_source = {}
    for run in db.list_recent_discovery_runs(limit=500):
        if run.get("run_id") != run_id:
            continue
        key = run.get("source_id")
        agg = per_source.setdefault(key, {
            "found": 0, "created": 0, "duplicates": 0,
        })
        agg["found"] += run.get("raw_items") or 0
        agg["created"] += run.get("stored_new") or 0
        agg["duplicates"] += run.get("duplicates") or 0
    for job in db.list_crawl_jobs(status="QUEUED"):
        if job.get("run_id") != run_id:
            continue
        agg = per_source.get(job.get("source_id")) or {}
        db.complete_crawl_job(
            job["id"],
            items_found=agg.get("found", 0),
            items_created=agg.get("created", 0),
            duplicates_found=agg.get("duplicates", 0),
        )
    return len(per_source)