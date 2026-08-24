import json
import os
import urllib.error

import pytest

from src import ai, db


def _opp(**overrides):
    opp = {
        "id": 1,
        "title": "ML Research Intern",
        "organization": "Modal",
        "description": "Work on ML infra",
        "eligibility_status": "unknown",
        "deadline": None,
        "funding": "Stipend provided",
        "location": "Remote",
    }
    opp.update(overrides)
    return opp


class TestParseJson:
    def test_plain_json(self):
        text = '{"verdict": "eligible", "reason": "ok", "deadline_guess": null, "confidence": 0.9}'
        assert ai._parse_json(text)["verdict"] == "eligible"

    def test_fenced_json(self):
        text = '```json\n{"verdict": "not_eligible"}\n```'
        assert ai._parse_json(text)["verdict"] == "not_eligible"

    def test_json_inside_prose(self):
        text = 'Sure! Here is the result: {"verdict": "unknown", "reason": "no data"} done.'
        assert ai._parse_json(text)["reason"] == "no data"

    def test_garbage(self):
        assert ai._parse_json("sorry, I cannot do that") is None
        assert ai._parse_json(None) is None

    def test_invalid_json_object(self):
        assert ai._parse_json('{"verdict": broken') is None


class _FakeResp:
    status = 200

    def read(self):
        return json.dumps({"models": [{"name": ai.DEFAULT_MODEL}]}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeChatResp(_FakeResp):
    def __init__(self, content):
        self._content = content

    def read(self):
        return json.dumps({"message": {"content": self._content}}).encode()


class TestAssess:
    def _mock_ollama(self, monkeypatch, response_text, available=True):
        def fake_urlopen(req, timeout=None):
            target = req.full_url if hasattr(req, "full_url") else str(req)
            if "tags" in target:
                return _FakeResp()
            return _FakeChatResp(response_text)

        monkeypatch.setattr(ai.urllib.request, "urlopen", fake_urlopen)
        return fake_urlopen

    def test_valid_assessment(self, tmp_db, monkeypatch):
        self._mock_ollama(monkeypatch, (
            '```json\n{"verdict": "likely_eligible", "reason": "undergrad ok", '
            '"deadline_guess": "2027-01-15", "confidence": 0.7}\n```'
        ))
        result = ai.assess(_opp())
        assert result == {
            "verdict": "likely_eligible",
            "reason": "undergrad ok",
            "deadline_guess": "2027-01-15",
            "confidence": 0.7,
        }

    def test_verdict_normalized(self, tmp_db, monkeypatch):
        self._mock_ollama(monkeypatch, (
            '{"verdict": "ELIGIBLE", "reason": "yes", "deadline_guess": null, "confidence": 1}'
        ))
        assert ai.assess(_opp())["verdict"] == "eligible"

    def test_invalid_verdict_falls_back_to_unclear(self, tmp_db, monkeypatch):
        self._mock_ollama(monkeypatch, (
            '{"verdict": "maybe?", "reason": "x", "deadline_guess": null, "confidence": 0.5}'
        ))
        assert ai.assess(_opp())["verdict"] == "unclear"

    def test_garbage_response_returns_none(self, tmp_db, monkeypatch):
        self._mock_ollama(monkeypatch, "I am sorry, I do not know.")
        assert ai.assess(_opp()) is None

    def test_unavailable_returns_none(self, tmp_db, monkeypatch):
        def boom(req, timeout=None):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr(ai.urllib.request, "urlopen", boom)
        assert ai.assess(_opp()) is None

    def test_confidence_clamped(self, tmp_db, monkeypatch):
        self._mock_ollama(monkeypatch, (
            '{"verdict": "eligible", "reason": "y", "deadline_guess": null, "confidence": 5}'
        ))
        assert ai.assess(_opp())["confidence"] == 1.0

    def test_bad_deadline_guess_ok(self, tmp_db, monkeypatch):
        self._mock_ollama(monkeypatch, (
            '{"verdict": "unknown", "reason": "y", "deadline_guess": "someday", "confidence": 0.2}'
        ))
        result = ai.assess(_opp())
        assert result["verdict"] == "unclear"


class TestAssessNew:
    def _seed_opp(self, title="T", eligibility="unknown"):
        return db.upsert_opportunity({
            "title": title, "organization": "Org", "type": "fellowship",
            "application_url": "https://org.example/x",
            "eligibility_status": eligibility,
        })

    def test_assesses_new_and_skips_existing(self, tmp_db, monkeypatch):
        opp_id = self._seed_opp()
        self._seed_opp(title="Second")
        self._seed_opp(title="Not eligible", eligibility="not_eligible")

        def fake_urlopen(req, timeout=None):
            target = req.full_url if hasattr(req, "full_url") else str(req)
            if "tags" in target:
                return _FakeResp()
            return _FakeChatResp(
                '{"verdict": "eligible", "reason": "ok", "deadline_guess": null, "confidence": 0.8}'
            )

        monkeypatch.setattr(ai.urllib.request, "urlopen", fake_urlopen)
        assert ai.assess_new(limit=10) == 2
        conn = db.get_connection()
        rows = conn.execute("SELECT opportunity_id, verdict FROM ai_assessments").fetchall()
        conn.close()
        assert len(rows) == 2
        assert {r["opportunity_id"] for r in rows} == {opp_id, opp_id + 1}
        assert all(r["verdict"] == "eligible" for r in rows)
        assert ai.assess_new(limit=10) == 0

    def test_limit_respected(self, tmp_db, monkeypatch):
        for i in range(4):
            self._seed_opp(title=f"Opp {i}")

        def fake_urlopen(req, timeout=None):
            target = req.full_url if hasattr(req, "full_url") else str(req)
            if "tags" in target:
                return _FakeResp()
            return _FakeChatResp(
                '{"verdict": "unknown", "reason": "ok", "deadline_guess": null, "confidence": 0.1}'
            )

        monkeypatch.setattr(ai.urllib.request, "urlopen", fake_urlopen)
        assert ai.assess_new(limit=3) == 3
        assert ai.assess_new(limit=3) == 1

    def test_unavailable_returns_zero(self, tmp_db, monkeypatch):
        self._seed_opp()
        monkeypatch.setattr(ai, "is_available", lambda url=None, timeout=3: False)
        assert ai.assess_new(limit=10) == 0


class TestWorkerIntegration:
    def test_pipeline_includes_ai(self, monkeypatch, tmp_db, capsys):
        import src.worker as worker
        monkeypatch.setattr("src.discovery.fellowship_scout.run", lambda **k: 3)
        monkeypatch.setattr("src.discovery.internship_scout.run", lambda **k: 2)
        monkeypatch.setattr(
            "src.discovery.hackathon_scout.run", lambda **k: 0
        )
        monkeypatch.setattr("src.notifications.notifier.run", lambda: 1)
        monkeypatch.setattr("src.ai.assess_new", lambda limit=5: 4)
        monkeypatch.setattr("src.verification.verify_due", lambda limit=20: {})
        monkeypatch.setattr(
            "src.discovery.enrichment.run_enrichment",
            lambda limit=15: {"candidates": 0, "filled": 0, "confirmed": 0,
                              "conflicts": 0, "unreadable": 0, "no_change": 0})
        summary = worker.run_pipeline()
        assert summary["ai_assessments"] == 4
        assert json.loads(capsys.readouterr().out)["ai_assessments"] == 4