"""Agent Orchestrator — manages task routing, dependencies, retries, and health.

The orchestrator is the central coordinator for all 16 agents. It:
- Routes tasks to the appropriate agent
- Manages task dependencies (e.g., extraction before classification)
- Handles retries with exponential backoff
- Monitors agent health
- Publishes events for downstream consumers
"""
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from src import db
from src.agents.base import (
    BaseAgent, AgentStatus, AgentCategory, AgentHealth,
    AgentEvent, AgentResult,
)

logger = logging.getLogger(__name__)


class PipelineStage:
    """Defines a stage in the opportunity processing pipeline."""

    def __init__(self, agent_id: str, depends_on: List[str] = None):
        self.agent_id = agent_id
        self.depends_on = depends_on or []


# The standard opportunity processing pipeline
PIPELINE = [
    PipelineStage("discovery_agent"),
    PipelineStage("crawler_agent", depends_on=["discovery_agent"]),
    PipelineStage("extraction_agent", depends_on=["crawler_agent"]),
    PipelineStage("classification_agent", depends_on=["extraction_agent"]),
    PipelineStage("eligibility_agent", depends_on=["extraction_agent"]),
    PipelineStage("deadline_agent", depends_on=["extraction_agent"]),
    PipelineStage("source_verification_agent", depends_on=["extraction_agent"]),
    PipelineStage("duplicate_agent", depends_on=["extraction_agent", "classification_agent"]),
    PipelineStage("quality_control_agent", depends_on=[
        "extraction_agent", "classification_agent", "eligibility_agent",
        "deadline_agent", "source_verification_agent", "duplicate_agent",
    ]),
    PipelineStage("trust_score_agent", depends_on=[
        "source_verification_agent", "quality_control_agent",
    ]),
]


class AgentOrchestrator:
    """Central orchestrator for the AAWARA agent system."""

    def __init__(self):
        self._agents: Dict[str, BaseAgent] = {}
        self._task_queue: List[dict] = []
        self._active_tasks: Dict[str, dict] = {}

    def register_agent(self, agent: BaseAgent):
        """Register an agent with the orchestrator."""
        self._agents[agent.AGENT_ID] = agent
        logger.info("Registered agent: %s (%s)", agent.AGENT_NAME, agent.AGENT_ID)

    def get_agent(self, agent_id: str) -> Optional[BaseAgent]:
        return self._agents.get(agent_id)

    def get_all_agents(self) -> List[BaseAgent]:
        return list(self._agents.values())

    def run_agent(self, agent_id: str, input_data: dict,
                  task_id: str = None) -> AgentResult:
        """Run a single agent with the given input."""
        agent = self._agents.get(agent_id)
        if not agent:
            return AgentResult(
                agent_id=agent_id,
                status=AgentStatus.FAILED,
                error=f"Agent {agent_id} not registered",
            )
        if agent.status == AgentStatus.DISABLED:
            return AgentResult(
                agent_id=agent_id,
                status=AgentStatus.FAILED,
                error=f"Agent {agent_id} is disabled",
            )
        return agent.run(input_data, task_id=task_id)

    def run_pipeline(self, initial_input: dict,
                     stages: List[PipelineStage] = None) -> dict:
        """Run the full opportunity processing pipeline.

        Each stage receives the accumulated context from previous stages.
        Returns a summary with results from each stage.
        """
        stages = stages or PIPELINE
        run_id = str(uuid.uuid4())[:8]
        context = dict(initial_input)
        results = {}
        started_at = datetime.now(timezone.utc).isoformat()

        for stage in stages:
            # Check dependencies
            deps_met = all(dep in results for dep in stage.depends_on)
            if not deps_met:
                logger.warning(
                    "Skipping %s: dependencies not met (%s)",
                    stage.agent_id, stage.depends_on,
                )
                results[stage.agent_id] = {
                    "status": "skipped",
                    "reason": "dependencies_not_met",
                }
                continue

            # Prepare input from context
            agent_input = self._prepare_input(stage.agent_id, context)

            # Run the agent
            result = self.run_agent(stage.agent_id, agent_input)
            results[stage.agent_id] = result.to_dict()

            # Update context with results
            if result.status == AgentStatus.COMPLETED and result.data:
                context[f"{stage.agent_id}_result"] = result.data

        finished_at = datetime.now(timezone.utc).isoformat()

        # Record pipeline run
        try:
            conn = db.get_connection()
            try:
                conn.execute(
                    "INSERT INTO agent_events "
                    "(event_type, agent_id, data, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        "pipeline.completed",
                        "orchestrator",
                        json.dumps({
                            "run_id": run_id,
                            "stages": len(results),
                            "results": {
                                k: v.get("status", "unknown")
                                for k, v in results.items()
                            },
                        }),
                        finished_at,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("Failed to record pipeline run: %s", exc)

        return {
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "stages": results,
        }

    def _prepare_input(self, agent_id: str, context: dict) -> dict:
        """Prepare input for a specific agent based on context."""
        if agent_id == "discovery_agent":
            return context
        if agent_id == "crawler_agent":
            return {
                "sources": context.get("discovery_agent_result", {}).get("sources", []),
                **context,
            }
        if agent_id == "extraction_agent":
            return {
                "pages": context.get("crawler_agent_result", {}).get("pages", []),
                **context,
            }
        if agent_id in ("classification_agent", "eligibility_agent",
                        "deadline_agent", "source_verification_agent"):
            return {
                "opportunity": context.get("extraction_agent_result", {}),
                **context,
            }
        if agent_id == "duplicate_agent":
            return {
                "opportunity": context.get("extraction_agent_result", {}),
                "classification": context.get("classification_agent_result", {}),
                **context,
            }
        if agent_id == "quality_control_agent":
            return {
                "opportunity": context.get("extraction_agent_result", {}),
                "classification": context.get("classification_agent_result", {}),
                "eligibility": context.get("eligibility_agent_result", {}),
                "deadline": context.get("deadline_agent_result", {}),
                "verification": context.get("source_verification_agent_result", {}),
                "duplicate": context.get("duplicate_agent_result", {}),
                **context,
            }
        if agent_id == "trust_score_agent":
            return {
                "opportunity": context.get("extraction_agent_result", {}),
                "verification": context.get("source_verification_agent_result", {}),
                "qc": context.get("quality_control_agent_result", {}),
                **context,
            }
        return context

    def get_all_metrics(self) -> List[dict]:
        """Get metrics for all registered agents."""
        return [agent.get_metrics() for agent in self._agents.values()]

    def get_pipeline_status(self) -> dict:
        """Get the current status of the pipeline."""
        return {
            "registered_agents": len(self._agents),
            "agents": {
                agent_id: {
                    "status": agent.status.value,
                    "health": agent.get_health().value,
                }
                for agent_id, agent in self._agents.items()
            },
        }


# Singleton orchestrator
_orchestrator = None


def get_orchestrator() -> AgentOrchestrator:
    """Get the global orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AgentOrchestrator()
    return _orchestrator


def init_orchestrator():
    """Initialize the orchestrator with all 16 agents."""
    from src.agents.discovery import DiscoveryAgent
    from src.agents.crawler import CrawlerAgent
    from src.agents.extraction import ExtractionAgent
    from src.agents.classification import ClassificationAgent
    from src.agents.eligibility import EligibilityAgent
    from src.agents.deadline import DeadlineAgent
    from src.agents.source_verification import SourceVerificationAgent
    from src.agents.duplicate import DuplicateAgent
    from src.agents.quality_control import QualityControlAgent
    from src.agents.trust_score import TrustScoreAgent
    from src.agents.recommendation import RecommendationAgent
    from src.agents.natural_language_search import NaturalLanguageSearchAgent
    from src.agents.freshness import FreshnessAgent
    from src.agents.change_detection import ChangeDetectionAgent
    from src.agents.user_support import UserSupportAgent
    from src.agents.application_assistant import ApplicationAssistant

    orch = get_orchestrator()
    for agent_cls in [
        DiscoveryAgent, CrawlerAgent, ExtractionAgent, ClassificationAgent,
        EligibilityAgent, DeadlineAgent, SourceVerificationAgent,
        DuplicateAgent, QualityControlAgent, TrustScoreAgent,
        RecommendationAgent, NaturalLanguageSearchAgent,
        FreshnessAgent, ChangeDetectionAgent,
        UserSupportAgent, ApplicationAssistant,
    ]:
        orch.register_agent(agent_cls())

    return orch
