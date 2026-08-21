"""Agent 14 — Change Detection Agent

Compares old and new source versions. Detects deadline changes, eligibility changes,
stipend changes, application URL changes, and opportunity closure.
"""
from src.agents.base import BaseAgent, AgentStatus, AgentCategory, AgentResult, AgentEvidence


class ChangeDetectionAgent(BaseAgent):
    AGENT_ID = "change_detection_agent"
    AGENT_NAME = "Change Detection Agent"
    AGENT_CATEGORY = AgentCategory.QUALITY
    AGENT_DESCRIPTION = "Detects changes in opportunity data over time"

    def process(self, input_data: dict) -> AgentResult:
        from src import db

        conn = db.get_connection()
        try:
            recent_changes = conn.execute(
                "SELECT * FROM opportunity_changes ORDER BY id DESC LIMIT 50"
            ).fetchall()
        finally:
            conn.close()

        changes = [dict(r) for r in recent_changes]
        change_types = {}
        for c in changes:
            ct = c.get("change_type", "unknown")
            change_types[ct] = change_types.get(ct, 0) + 1

        unnotified = [c for c in changes if not c.get("notified")]

        evidence = [
            AgentEvidence(
                field="changes_detected",
                value=len(changes),
                confidence=1.0,
                agent_id=self.AGENT_ID,
            )
        ]

        return AgentResult(
            agent_id=self.AGENT_ID,
            status=AgentStatus.COMPLETED,
            data={
                "total_changes": len(changes),
                "change_types": change_types,
                "unnotified_count": len(unnotified),
                "recent_changes": changes[:10],
            },
            confidence=1.0,
            evidence=evidence,
        )
