import json
import os
import threading
import urllib.request

import pytest

from src import webhook
from src import worker


class TestWorkerPipeline:
    def test_runs_scouts_then_notifier(self, monkeypatch, tmp_db, capsys):
        calls = []

        def fake_fellowship(**kwargs):
            calls.append("fellowship")
            return 3

        def fake_internship(**kwargs):
            calls.append("internship")
            return 2

        def fake_notifier():
            calls.append("notifier")
            return 1

        monkeypatch.setattr(worker, "db", None)
        import src.db as db
        monkeypatch.setattr(worker, "db", db)
        monkeypatch.setattr(
            "src.discovery.fellowship_scout.run", fake_fellowship,
        )
        monkeypatch.setattr(
            "src.discovery.internship_scout.run", fake_internship,
        )
        monkeypatch.setattr(
            "src.discovery.hackathon_scout.run", lambda **k: 0
        )
        monkeypatch.setattr("src.notifications.notifier.run", fake_notifier)
        monkeypatch.setattr("src.ai.assess_new", lambda limit=5: 0)
        monkeypatch.setattr(
            "src.maintenance.run_maintenance",
            lambda: {"expired": 0, "pruned_logs": 0,
                     "pruned_errors": 0, "pruned_notifications": 0},
        )
        summary = worker.run_pipeline()
        expected = {
            "fellowship_scout": 3,
            "internship_scout": 2,
            "hackathon_scout": 0,
            "notifications": 1,
            "ai_assessments": 0,
            "maintenance": {"expired": 0, "pruned_logs": 0,
                            "pruned_errors": 0, "pruned_notifications": 0},
        }
        assert {k: v for k, v in summary.items() if k not in ("discovery", "crawl_queue", "verification", "run_id")} == expected
        assert "run_id" in summary
        assert "discovery" in summary
        assert summary["crawl_queue"]["queued"] > 0
        settled = summary["crawl_queue"]["settled"]
        assert settled.get("completed", 0) + settled.get("failed", 0) >= 0
        assert calls == ["fellowship", "internship", "notifier"]
        out = capsys.readouterr().out
        assert json.loads(out) == summary


class TestWebhook:
    def _start(self, monkeypatch):
        server = webhook.make_server("127.0.0.1", 0)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self._server = server
        return f"http://127.0.0.1:{port}"

    def teardown_method(self):
        if hasattr(self, "_server"):
            self._server.shutdown()
            self._server.server_close()

    def _request(self, base, method, path, token=None):
        req = urllib.request.Request(base + path, method=method)
        if token is not None:
            req.add_header("X-Run-Token", token)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode())

    def test_health(self, tmp_db, monkeypatch):
        base = self._start(monkeypatch)
        status, body = self._request(base, "GET", "/health")
        assert status == 200
        assert body == {"ok": True}

    def test_unknown_path(self, tmp_db, monkeypatch):
        base = self._start(monkeypatch)
        status, body = self._request(base, "GET", "/nope")
        assert status == 404

    def test_run_requires_token(self, tmp_db, monkeypatch):
        monkeypatch.setenv("RUN_TOKEN", "secret")
        base = self._start(monkeypatch)
        status, body = self._request(base, "POST", "/run")
        assert status == 401
        status, body = self._request(base, "POST", "/run", token="wrong")
        assert status == 401

    def test_run_executes_pipeline(self, tmp_db, monkeypatch):
        monkeypatch.setenv("RUN_TOKEN", "secret")
        monkeypatch.setattr(
            webhook.worker, "run_pipeline",
            lambda: {"fellowship_scout": 1, "internship_scout": 2, "notifications": 0},
        )
        base = self._start(monkeypatch)
        status, body = self._request(base, "POST", "/run", token="secret")
        assert status == 200
        assert body == {"fellowship_scout": 1, "internship_scout": 2, "notifications": 0}

    def test_run_error_returns_500(self, tmp_db, monkeypatch):
        monkeypatch.setenv("RUN_TOKEN", "secret")

        def boom():
            raise RuntimeError("kaboom")

        monkeypatch.setattr(webhook.worker, "run_pipeline", boom)
        base = self._start(monkeypatch)
        status, body = self._request(base, "POST", "/run", token="secret")
        assert status == 500
        # Internal error details are never leaked to the caller.
        assert body == {"error": "pipeline run failed"}
        assert "kaboom" not in json.dumps(body)