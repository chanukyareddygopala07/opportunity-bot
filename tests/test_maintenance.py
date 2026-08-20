import json
from datetime import datetime, timedelta, timezone

from src import db, maintenance
from src.notifications import formatting


def _opp(deadline=None, status="new", title="T"):
    return db.upsert_opportunity({
        "title": title, "organization": "Org", "type": "internship",
        "application_url": "https://example.com/x",
        "deadline": deadline, "status": status,
    })


class TestRunMaintenance:
    def test_expired_marked(self, tmp_db):
        past = _opp(deadline="2020-01-01")
        future = _opp(deadline="2999-01-01", status="seen", title="Future")
        result = maintenance.run_maintenance()
        assert result["expired"] == 1
        assert db.get_opportunity(past)["status"] == "expired"
        assert db.get_opportunity(future)["status"] == "seen"

    def test_expired_only_new_or_seen(self, tmp_db):
        closed = _opp(deadline="2020-01-01", status="closed", title="Closed")
        maintenance.run_maintenance()
        assert db.get_opportunity(closed)["status"] == "closed"

    def test_retention_prunes_old_rows(self, tmp_db):
        old = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
        fresh = db.now_iso()
        conn = db.get_connection()
        conn.execute(
            "INSERT INTO execution_logs (run_id, workflow, step, status, message, started_at) "
            "VALUES ('old', 'worker', 'pipeline', 'success', 'x', ?), "
            "('new', 'worker', 'pipeline', 'success', 'x', ?)",
            (old, fresh),
        )
        conn.execute(
            "INSERT INTO system_errors (component, error_type, message, occurred_at) "
            "VALUES ('worker', 'X', 'x', ?), ('worker', 'X', 'x', ?)",
            (old, fresh),
        )
        conn.execute(
            "INSERT INTO notifications (opportunity_id, kind, message, sent_at) "
            "VALUES (NULL, 'new_opportunity', 'x', ?), (NULL, 'new_opportunity', 'x', ?)",
            (old, fresh),
        )
        conn.commit()
        conn.close()
        result = maintenance.run_maintenance()
        assert result["pruned_logs"] == 1
        assert result["pruned_errors"] == 1
        assert result["pruned_notifications"] == 1
        conn = db.get_connection()
        assert conn.execute("SELECT COUNT(*) FROM execution_logs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM system_errors").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == 1
        conn.close()

    def test_idempotent(self, tmp_db):
        _opp(deadline="2020-01-01")
        maintenance.run_maintenance()
        result = maintenance.run_maintenance()
        assert result["expired"] == 0


class TestStats:
    def test_stats_payload(self, tmp_db):
        from src import webhook
        opp_id = db.upsert_opportunity({
            "title": "A", "organization": "O", "type": "internship",
            "application_url": "https://example.com/a",
            "verification_status": "verified",
        })
        db.update_opportunity(opp_id, saved=1)
        db.log_execution("r1", "worker", "pipeline", "success",
                         '{"fellowship_scout": 2, "internship_scout": 3, '
                         '"notifications": 0, "ai_assessments": 1}')
        payload = webhook.stats_payload()
        assert payload["counts"]["opportunities"] == 1
        assert payload["counts"]["verified"] == 1
        assert payload["counts"]["saved"] == 1
        assert payload["last_pipeline"]["message"].startswith("{")

    def test_stats_text(self, tmp_db):
        from src import webhook
        text = formatting.stats_text(webhook.stats_payload())
        assert "Bot stats" in text
        assert "Opportunities:" in text


class TestWorkerPipelineMaintenance:
    def test_pipeline_logs_run_and_runs_maintenance(self, monkeypatch, tmp_db):
        import src.worker as worker
        monkeypatch.setattr("src.discovery.fellowship_scout.run", lambda **k: 0)
        monkeypatch.setattr("src.discovery.internship_scout.run", lambda **k: 0)
        monkeypatch.setattr("src.notifications.notifier.run", lambda: 0)
        monkeypatch.setattr("src.ai.assess_new", lambda limit=5: 0)
        monkeypatch.setattr("src.maintenance.run_maintenance",
                            lambda: {"expired": 1, "pruned_logs": 0,
                                     "pruned_errors": 0, "pruned_notifications": 0})
        summary = worker.run_pipeline()
        assert summary["maintenance"] == {"expired": 1, "pruned_logs": 0,
                                          "pruned_errors": 0, "pruned_notifications": 0}
        conn = db.get_connection()
        row = conn.execute(
            "SELECT * FROM execution_logs WHERE workflow = 'worker' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        assert row["status"] == "success"
        assert json.loads(row["message"])["maintenance"]["expired"] == 1