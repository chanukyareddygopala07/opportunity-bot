"""Agent 01 — Discovery Agent

Finds potentially relevant opportunity sources and URLs.
Uses the existing source registry and discovery system.
"""
from src.agents.base import BaseAgent, AgentStatus, AgentCategory, AgentResult, AgentEvidence


class DiscoveryAgent(BaseAgent):
    AGENT_ID = "discovery_agent"
    AGENT_NAME = "Discovery Agent"
    AGENT_CATEGORY = AgentCategory.DISCOVERY
    AGENT_DESCRIPTION = "Finds potentially relevant opportunity sources and URLs"

    def process(self, input_data: dict) -> AgentResult:
        from src import sources as registry, db

        query = input_data.get("query", "")
        country = input_data.get("country", "India")
        category = input_data.get("category", "")

        registry.sync_sources()
        sources = registry.list_enabled_sources(category=category if category else None)

        discovered = []
        for src in sources:
            if not src.get("url"):
                continue
            discovered.append({
                "url": src["url"],
                "domain": src.get("url", "").split("//")[-1].split("/")[0],
                "organization": src.get("organization", ""),
                "source_type": src.get("type", "unknown"),
                "trust_score": src.get("trust_score", 50),
                "name": src.get("name", ""),
                "method": src.get("method", ""),
                "priority": src.get("priority", 0),
            })

        evidence = [
            AgentEvidence(
                field="sources_discovered",
                value=len(discovered),
                confidence=1.0,
                agent_id=self.AGENT_ID,
            )
        ]

        return AgentResult(
            agent_id=self.AGENT_ID,
            status=AgentStatus.COMPLETED,
            data={
                "sources": discovered,
                "total": len(discovered),
                "country": country,
                "category": category,
            },
            confidence=1.0,
            evidence=evidence,
        )
