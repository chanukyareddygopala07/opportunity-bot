"""Crawl job queue — plans and settles the crawl work for a pipeline run.

The queue is a first-class record of what we intend to crawl and with which
crawler (router decision). Scouts execute the work; settle() copies the real
counts from discovery_runs back onto the jobs and marks failures so the queue
stays honest. Failures with retry budget left become RETRYING and are
re-queued automatically on the next run; exhausted jobs stay FAILED (the
admin can retry them manually).
"""
import logging

from src import db, sources as registry
from src.discovery import router

logger = logging.getLogger(__name__)

# A QUEUED job older than this belongs to a crashed/superseded run; it must
# never block enqueueing forever.
STALE_JOB_HOURS = 6
MAX_RETRIES = 3


def recover_stale_jobs():
    """Free the queue from crashed runs before planning a new one.

    - RETRYING jobs from earlier runs        -> QUEUED again (this is their retry;
      they get a fresh started_at so the staleness check below spares them).
    - QUEUED jobs older than STALE_JOB_HOURS -> retry budget respected
      (RETRYING with fresh budget, or FAILED when exhausted).

    Returns (expired, reactivated) counts.
    """
    reactivated = db.reactivate_retrying_crawl_jobs()
    expired = db.expire_stale_crawl_jobs(max_age_hours=STALE_JOB_HOURS)
    if expired or reactivated:
        logger.info("queue recovery: %d stale job(s) expired, %d retried",
                    expired, reactivated)
    return expired, reactivated


def enqueue_from_sources(run_id):
    """Queue one job per enabled source for this run (skips if already queued)."""
    registry.sync_sources()
    recover_stale_jobs()
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
    """Reconcile this run's jobs with what actually happened per source.

    Uses the discovery_runs rows recorded by the scouts under the same
    run_id: a row with an error fails its job (with retry budget), a clean
    row completes it with real counts, and a missing row means the scout
    never reached that source.
    """
    per_source = {}
    for run in db.list_discovery_runs_for_run(run_id):
        key = run.get("source_id")
        agg = per_source.setdefault(key, {
            "found": 0, "created": 0, "duplicates": 0, "error": None,
        })
        agg["found"] += run.get("raw_items") or 0
        agg["created"] += run.get("stored_new") or 0
        agg["duplicates"] += run.get("duplicates") or 0
        if run.get("error"):
            agg["error"] = run.get("error")

    completed = failed = missing = 0
    for job in db.list_crawl_jobs(status="QUEUED"):
        if job.get("run_id") != run_id:
            continue
        agg = per_source.get(job.get("source_id"))
        if agg is None:
            # Scout never produced a result row for this source.
            db.fail_crawl_job(job["id"], "no discovery_run recorded for source")
            failed += 1
            missing += 1
        elif agg.get("error"):
            db.fail_crawl_job(job["id"], agg["error"])
            failed += 1
        else:
            db.complete_crawl_job(
                job["id"],
                items_found=agg.get("found", 0),
                items_created=agg.get("created", 0),
                duplicates_found=agg.get("duplicates", 0),
            )
            completed += 1
    return {"completed": completed, "failed": failed}
