"""Orchestrator pipeline contract regression tests (P0-0.7).

Guards the fix for the broken inter-stage contract where downstream agents
received the extraction wrapper dict instead of a single opportunity.
"""
import json

import pytest

from src import db
from src.agents.base import AgentResult, AgentStatus
from src.agents.orchestrator import AgentOrchestrator, init_orchestrator


SAMPLE_OPPORTUNITY = {
    "title": "ML Research Intern",
    "organization": "Acme AI",
    "description": "6 month research internship. Stipend of 40000 per month.",
    "source_url": "https://acme.example/careers/ml-intern",
    "application_url": "https://acme.example/apply/123",
    "source_type": "official_company",
}


@pytest.fixture()
def orch(tmp_db):
    return init_orchestrator()


def _mock_upstream(monkeypatch, opportunities):
    """Discovery returns one source; crawler returns its page; extraction is real."""
    from src.agents.discovery import DiscoveryAgent
    from src.agents.crawler import CrawlerAgent

    def fake_discovery(self, input_data):
        return AgentResult(
            agent_id=self.AGENT_ID,
            status=AgentStatus.COMPLETED,
            data={"sources": [{
                "id": 1, "name": "Acme", "url": "https://acme.example",
                "organization": "Acme AI", "type": "official_company",
                "method": "html_links", "category": "internship",
            }]},
        )

    def fake_crawler(self, input_data):
        return AgentResult(
            agent_id=self.AGENT_ID,
            status=AgentStatus.COMPLETED,
            data={"pages": [{
                "url": "https://acme.example/careers/ml-intern",
                "content": "<html><title>ML Research Intern</title></html>",
                "source": {"id": 1, "name": "Acme", "organization": "Acme AI",
                           "type": "official_company"},
            }]},
        )

    monkeypatch.setattr(DiscoveryAgent, "process", fake_discovery)
    monkeypatch.setattr(CrawlerAgent, "process", fake_crawler)
    # Extraction is forced to yield our canned opportunity list so the test
    # focuses on the inter-stage contract, not regex quality.
    from src.agents.extraction import ExtractionAgent

    def fake_extraction(self, input_data):
        return AgentResult(
            agent_id=self.AGENT_ID,
            status=AgentStatus.COMPLETED,
            data={"opportunities": opportunities, "total": len(opportunities),
                  "valid": len(opportunities)},
            confidence=1.0,
        )

    monkeypatch.setattr(ExtractionAgent, "process", fake_extraction)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Hermetic tests: stub the link checker used by SourceVerificationAgent."""
    monkeypatch.setattr(
        "src.verification.check_link", lambda url: ("dead", "test stub"))


def test_downstream_stages_receive_opportunity_not_wrapper(orch, monkeypatch):
    _mock_upstream(monkeypatch, [dict(SAMPLE_OPPORTUNITY)])
    summary = orch.run_pipeline({})
    # The per-opportunity stages must have run on the actual opportunity.
    processed = summary["opportunities"]
    assert len(processed) == 1
    item = processed[0]
    assert item["title"] == "ML Research Intern"
    for stage_id in ("classification_agent", "eligibility_agent", "deadline_agent"):
        stage = item["stages"][stage_id]
        assert stage["status"] == AgentStatus.COMPLETED.value, stage


def test_duplicate_agent_receives_opportunity_with_title(orch, monkeypatch):
    """DuplicateAgent short-circuits only when the id is missing — but it must
    at least SEE the title (the old bug passed it a wrapper with title=None)."""
    _mock_upstream(monkeypatch, [dict(SAMPLE_OPPORTUNITY)])
    seen = {}

    from src.agents.duplicate import DuplicateAgent

    def spy(self, input_data):
        seen["opportunity"] = input_data.get("opportunity")
        return self.__class__.process(self, input_data)

    monkeypatch.setattr(DuplicateAgent, "process", spy)
    orch.run_pipeline({})
    assert seen["opportunity"] is not None
    assert seen["opportunity"].get("title") == "ML Research Intern"


def test_multiple_opportunities_each_processed(orch, monkeypatch):
    opps = [
        dict(SAMPLE_OPPORTUNITY),
        {**SAMPLE_OPPORTUNITY, "title": "Backend Intern",
         "source_url": "https://acme.example/careers/be"},
    ]
    _mock_upstream(monkeypatch, opps)
    summary = orch.run_pipeline({})
    titles = [o["title"] for o in summary["opportunities"]]
    assert titles == ["ML Research Intern", "Backend Intern"]


def test_failed_extraction_skips_downstream(orch, monkeypatch):
    _mock_upstream(monkeypatch, [dict(SAMPLE_OPPORTUNITY)])
    from src.agents.extraction import ExtractionAgent

    def failing_extraction(self, input_data):
        return AgentResult(
            agent_id=self.AGENT_ID,
            status=AgentStatus.FAILED,
            error="no pages",
        )

    monkeypatch.setattr(ExtractionAgent, "process", failing_extraction)
    summary = orch.run_pipeline({})
    assert summary["totals"]["opportunities_processed"] == 0
    shared = summary["shared_stages"]
    for stage_id in ("classification_agent", "eligibility_agent",
                     "trust_score_agent"):
        assert stage_id not in shared  # never ran as a shared stage


def test_pipeline_records_event(tmp_db, orch, monkeypatch):
    _mock_upstream(monkeypatch, [dict(SAMPLE_OPPORTUNITY)])
    orch.run_pipeline({})
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT data FROM agent_events WHERE event_type = 'pipeline.completed'"
        ).fetchall()
    finally:
        conn.close()
    assert rows, "pipeline.completed event must be recorded"
    payload = json.loads(rows[-1]["data"])
    assert payload["opportunities_processed"] == 1
