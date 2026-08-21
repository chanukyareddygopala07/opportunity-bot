"""AAWARA Agent System — 16 specialized agents for opportunity intelligence.

Each agent is a self-contained module that:
1. Receives structured input
2. Processes using deterministic logic (preferred) or AI (when needed)
3. Returns structured output with confidence and evidence
4. Never fabricates data — returns UNKNOWN/REVIEW_REQUIRED when uncertain

The agent orchestrator manages task routing, dependencies, retries, and health.
"""
from src.agents.base import BaseAgent, AgentStatus, AgentCategory
from src.agents.orchestrator import AgentOrchestrator

__all__ = ["BaseAgent", "AgentStatus", "AgentCategory", "AgentOrchestrator"]
