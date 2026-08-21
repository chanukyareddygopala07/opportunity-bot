"""Agent 10 — Trust Score Agent

Calculates trust score 0-100 from actual data components.
Never fabricates scores — uses real verification status, source type, etc.
"""
from src.agents.base import BaseAgent, AgentStatus, AgentCategory, AgentResult, AgentEvidence


class TrustScoreAgent(BaseAgent):
    AGENT_ID = "trust_score_agent"
    AGENT_NAME = "Trust Score Agent"
    AGENT_CATEGORY = AgentCategory.QUALITY
    AGENT_DESCRIPTION = "Calculates trust score 0-100 from actual data components"

    def process(self, input_data: dict) -> AgentResult:
        from src.trust import compute, trust_label

        opp = input_data.get("opportunity", {})
        score, label, components = compute(opp)

        evidence = [
            AgentEvidence(
                field="trust_score",
                value=score,
                source_url=opp.get("source_url"),
                confidence=1.0,
                agent_id=self.AGENT_ID,
            )
        ]

        return AgentResult(
            agent_id=self.AGENT_ID,
            status=AgentStatus.COMPLETED,
            data={
                "trust_score": score,
                "trust_label": label,
                "components": components,
            },
            confidence=1.0,
            evidence=evidence,
        )
