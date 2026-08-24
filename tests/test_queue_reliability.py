"""Queue reliability tests (P0-0.8): retries wired, stale recovery, honest settle."""
from datetime import datetime, timedelta, timezone

from src import db
from src import queue as crawl_queue


def _run_row(run_id, source_id, error=None, **kw):
    db.record_discovery_run(
        run_id=run_id, scout="internship_scout", source_id=source_id,
        source_name=f"S{source_id}", source_url=f"https://s{source_id}.example",
        method="static", raw_items=kw.get("raw_items", 1),
        stored_new=kw.get("stored_new", 0), duplicates=0, error=error,
    )


class TestSettle:
    def test_settle_fails_jobs_for_errored_sources(self, tmp_db):
        db.enqueue_crawl_job("r1", 7, "S7", "https://s7.example", "static", "high")
        _run_row("r1", 7, error="HTTPError: 500")
        result = crawl_queue.settle("r1")
        assert result == {"completed": 0, "failed": 1}
        job = db.list_crawl_jobs(status="RETRYING")[0]
        assert job["retry_count"] == 1
        assert "500" in job["error"]

    def test_settle_completes_clean_sources_with_real_counts(self, tmp_db):
        db.enqueue_crawl_job("r1", 8, "S8", "https://s8.example", "static", "medium")
        _run_row("r1", 8, raw_items=12, stored_new=4)
        result = crawl_queue.settle("r1")
        assert result["completed"] == 1
        done = db.list_crawl_jobs(status="COMPLETED")[0]
        assert done["items_found"] == 12
        assert done["items_created"] == 4

    def test_settle_fails_job_when_scout_never_ran(self, tmp_db):
        db.enqueue_crawl_job("r1", 9, "S9", "https://s9.example", "static", "low")
        result = crawl_queue.settle("r1")
        assert result == {"completed": 0, "failed": 1}
        assert db.list_crawl_jobs(status="RETRYING")[0]["error"] == \
            "no discovery_run recorded for source"

    def test_settle_leaves_other_runs_alone(self, tmp_db):
        db.enqueue_crawl_job("old", 1, "A", "https://a.example", "static", "medium")
        crawl_queue.settle("new-run")
        assert db.crawl_queue_stats().get("QUEUED") == 1

    def test_exhausted_retries_become_failed(self, tmp_db):
        db.enqueue_crawl_job("r1", 5, "S5", "https://s5.example", "static", "medium")
        _run_row("r1", 5, error="boom")
        for _ in range(crawl_queue.MAX_RETRIES):
            crawl_queue.settle("r1")
            db.reactivate_retrying_crawl_jobs()
        stats = db.crawl_queue_stats()
        assert stats.get("FAILED") == 1
        assert not stats.get("RETRYING")


class TestRecovery:
    def test_stale_queued_job_does_not_block_enqueueing(self, tmp_db):
        # A crashed run left this job QUEUED many hours ago.
        stale_time = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
        conn = db.get_connection()
        try:
            conn.execute(
                "INSERT INTO crawl_jobs (run_id, source_id, source_name, url, "
                "crawler, priority, status, started_at) "
                "VALUES ('crashed', 42, 'Old', 'https://old.example', 'static', "
                "'medium', 'QUEUED', ?)",
                (stale_time,),
            )
            conn.commit()
        finally:
            conn.close()
        # Recovery must clear it out of the way.
        expired, reactivated = crawl_queue.recover_stale_jobs()
        assert expired == 1
        assert db.crawl_queue_stats().get("QUEUED") is None

    def test_recent_queued_job_is_not_expired(self, tmp_db):
        db.enqueue_crawl_job("current", 1, "A", "https://a.example", "static", "high")
        expired, reactivated = crawl_queue.recover_stale_jobs()
        assert expired == 0
        assert db.crawl_queue_stats() == {"QUEUED": 1}

    def test_retrying_jobs_are_reactivated_as_queued(self, tmp_db):
        db.enqueue_crawl_job("r1", 2, "B", "https://b.example", "static", "medium")
        db.fail_crawl_job(1, "timeout")  # -> RETRYING
        expired, reactivated = crawl_queue.recover_stale_jobs()
        assert reactivated == 1
        assert db.crawl_queue_stats() == {"QUEUED": 1}

    def test_enqueue_skips_when_genuinely_queued(self, tmp_db, monkeypatch):
        monkeypatch.setattr(
            "src.queue.registry.list_enabled_sources", lambda *a, **k: [])
        db.enqueue_crawl_job("live", 3, "C", "https://c.example", "static", "high")
        assert crawl_queue.enqueue_from_sources("next") == 0
