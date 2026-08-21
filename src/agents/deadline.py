"""Agent 06 — Deadline Agent

Extracts and verifies deadlines. Uses timezone-aware datetime.
Never infers deadlines from publication dates or previous years.
"""
from src.agents.base import BaseAgent, AgentStatus, AgentCategory, AgentResult, AgentEvidence


class DeadlineAgent(BaseAgent):
    AGENT_ID = "deadline_agent"
    AGENT_NAME = "Deadline Agent"
    AGENT_CATEGORY = AgentCategory.INTELLIGENCE
    AGENT_DESCRIPTION = "Extracts and verifies deadlines with timezone-aware datetime"

    def process(self, input_data: dict) -> AgentResult:
        from src.deadlines import status, days_left, label

        opp = input_data.get("opportunity", {})
        deadline_str = opp.get("deadline")

        deadline_status = status(opp)
        days = days_left(deadline_str)
        deadline_label = label(deadline_status)

        evidence = []
        if deadline_str:
            evidence.append(AgentEvidence(
                field="deadline",
                value=deadline_str,
                source_url=opp.get("source_url"),
                confidence=0.9 if deadline_status != "UNKNOWN" else 0.3,
                agent_id=self.AGENT_ID,
            ))

        return AgentResult(
            agent_id=self.AGENT_ID,
            status=AgentStatus.COMPLETED,
            data={
                "deadline": deadline_str,
                "deadline_status": deadline_status,
                "deadline_days_left": days,
                "deadline_label": deadline_label,
                "start_date": opp.get("start_date"),
                "end_date": opp.get("end_date"),
            },
            confidence=0.9 if deadline_status in ("OPEN", "CLOSING_SOON", "CLOSED") else 0.4,
            evidence=evidence,
        )
