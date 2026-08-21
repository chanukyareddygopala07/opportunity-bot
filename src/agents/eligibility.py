"""Agent 05 — Eligibility Agent

Determines eligibility based on actual source information.
Never converts uncertainty to eligible — returns UNKNOWN when unsure.
"""
from src.agents.base import BaseAgent, AgentStatus, AgentCategory, AgentResult, AgentEvidence


class EligibilityAgent(BaseAgent):
    AGENT_ID = "eligibility_agent"
    AGENT_NAME = "Eligibility Agent"
    AGENT_CATEGORY = AgentCategory.INTELLIGENCE
    AGENT_DESCRIPTION = "Determines eligibility based on actual source information"

    def process(self, input_data: dict) -> AgentResult:
        from src.scoring import evaluate_eligibility

        opp = input_data.get("opportunity", {})
        profile = input_data.get("profile") or input_data.get("student_profile")

        if not profile:
            status = "unknown"
            reasons = ["no student profile provided"]
            missing = ["student_profile"]
        else:
            status, reasons, missing = evaluate_eligibility(opp, profile)

        evidence = [
            AgentEvidence(
                field="eligibility_status",
                value=status,
                source_url=opp.get("source_url"),
                confidence=0.9 if status in ("eligible", "not_eligible") else 0.5,
                agent_id=self.AGENT_ID,
            )
        ]

        return AgentResult(
            agent_id=self.AGENT_ID,
            status=AgentStatus.COMPLETED,
            data={
                "eligibility_status": status,
                "reasons": reasons,
                "missing_information": missing,
            },
            confidence=0.9 if status in ("eligible", "not_eligible") else 0.5,
            evidence=evidence,
        )
