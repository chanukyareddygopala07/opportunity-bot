"""Crawler router + crawl job queue tests."""
from src import db
from src.discovery import router


def test_ats_detection():
    assert router.select_crawler({"url": "https://boards.greenhouse.io/acme"}) == router.ATS
    assert router.select_crawler({"url": "https://jobs.lever.co/acme/role"}) == router.ATS
    assert router.select_crawler({"url": "https://jobs.ashbyhq.com/acme"}) == router.ATS


def test_method_overrides_url():
    assert router.select_crawler(
        {"url": "https://example.com/feed.xml", "method": "rss"}
    ) == router.AI_FRIENDLY
    assert router.select_crawler(
        {"url": "https://example.com/x", "method": "ats_greenhouse"}
    ) == router.ATS


def test_pdf_and_api():
    assert router.select_crawler({"url": "https://example.com/listings.pdf"}) == router.PDF
    assert router.select_crawler({"url": "https://api.example.com/v1/jobs.json"}) == router.API


def test_default_static():
    assert router.select_crawler({"url": "https://example.com/jobs"}) == router.STATIC


def test_robots_respected():
    assert router.select_crawler(
        {"url": "https://example.com/x"}, robots_disallowed=True
    ) == router.RESPECT_ROBOTS


def test_configured_crawler_wins():
    assert router.select_crawler(
        {"url": "https://example.com/x", "crawler": "playwright"}
    ) == router.JS_HEAVY


def test_priority():
    assert router.priority_for_source({"priority": "high"}) == "high"
    assert router.priority_for_source({"priority": "low"}) == "low"
    assert router.priority_for_source({}) == "medium"


def test_priority_bumps_for_near_deadline():
    assert router.priority_for_source({"priority": "low"}, recent_deadlines=[5]) == "high"
    assert router.priority_for_source({"priority": "low"}, recent_deadlines=[20]) == "medium"


class TestQueue:
    def test_enqueue_and_priority_order(self, tmp_db):
        db.enqueue_crawl_job("r1", 1, "A", "https://a", "static", "low")
        db.enqueue_crawl_job("r1", 2, "B", "https://b", "static", "high")
        db.enqueue_crawl_job("r1", 3, "C", "https://c", "static", "medium")
        jobs = db.next_crawl_jobs(10)
        assert [j["source_name"] for j in jobs] == ["B", "C", "A"]

    def test_complete_and_fail(self, tmp_db):
        db.enqueue_crawl_job("r1", 1, "A", "https://a", "static", "medium")
        job = db.next_crawl_jobs(1)[0]
        db.complete_crawl_job(job["id"], items_found=4, items_created=2)
        done = db.list_crawl_jobs(status="COMPLETED")[0]
        assert done["items_found"] == 4
        assert done["items_created"] == 2

        db.enqueue_crawl_job("r1", 2, "B", "https://b", "static", "medium")
        job = db.next_crawl_jobs(1)[0]
        db.fail_crawl_job(job["id"], "timeout")
        failed = db.list_crawl_jobs(status="RETRYING")[0]
        assert failed["retry_count"] == 1
        db.fail_crawl_job(job["id"], "timeout")
        db.fail_crawl_job(job["id"], "timeout")
        assert db.list_crawl_jobs(status="FAILED")[0]["retry_count"] == 3

    def test_queue_stats(self, tmp_db):
        db.enqueue_crawl_job("r1", 1, "A", "https://a", "static", "high")
        db.enqueue_crawl_job("r1", 2, "B", "https://b", "static", "high")
        assert db.crawl_queue_stats() == {"QUEUED": 2}

    def test_settle_copies_counts(self, tmp_db):
        db.enqueue_crawl_job("run1", 7, "S", "https://s", "static", "high")
        db.record_discovery_run(
            run_id="run1", scout="internship_scout", source_id=7,
            source_name="S", source_url="https://s", method="static",
            raw_items=5, stored_new=3, duplicates=1,
        )
        from src import queue as crawl_queue
        crawl_queue.settle("run1")
        done = db.list_crawl_jobs(status="COMPLETED")[0]
        assert done["items_found"] == 5
        assert done["items_created"] == 3
        assert done["duplicates_found"] == 1

    def test_deadline_days_active(self, tmp_db):
        db.upsert_opportunity({
            "title": "A", "organization": "O", "type": "internship",
            "application_url": "https://x.example/a", "deadline": "2099-01-01",
        })
        days = db.deadline_days_active()
        assert len(days) == 1
        assert days[0] > 0