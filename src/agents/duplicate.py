"""Agent 08 — Duplicate Agent

Detects duplicates using deterministic comparison first, AI only for ambiguous cases.
Never destroys source evidence.
"""
from src.agents.base import BaseAgent, AgentStatus, AgentCategory, AgentResult, AgentEvidence


class DuplicateAgent(BaseAgent):
    AGENT_ID = "duplicate_agent"
    AGENT_NAME = "Duplicate Agent"
    AGENT_CATEGORY = AgentCategory.QUALITY
    AGENT_DESCRIPTION = "Detects duplicates using deterministic comparison and semantic similarity"

    def process(self, input_data: dict) -> AgentResult:
        from src.dedupe import find_near_duplicates, mark_if_duplicate
        from src import db

        opp = input_data.get("opportunity", {})
        opp_id = opp.get("id")

        if not opp_id:
            return AgentResult(
                agent_id=self.AGENT_ID,
                status=AgentStatus.COMPLETED,
                data={"is_duplicate": False, "reason": "no opportunity id"},
                confidence=1.0,
            )

        candidates = find_near_duplicates(opp_id)
        is_duplicate = len(candidates) > 0
        duplicate_of = None
        similarity = 0.0

        if candidates:
            best_match, similarity = candidates[0]
            duplicate_of = best_match.get("id")

        evidence = []
        if is_duplicate:
            evidence.append(AgentEvidence(
                field="duplicate_detected",
                value=True,
                source_url=opp.get("source_url"),
                confidence=similarity,
                agent_id=self.AGENT_ID,
            ))

        return AgentResult(
            agent_id=self.AGENT_ID,
            status=AgentStatus.COMPLETED,
            data={
                "is_duplicate": is_duplicate,
                "duplicate_of": duplicate_of,
                "similarity": similarity,
                "candidates_count": len(candidates),
            },
            confidence=similarity if is_duplicate else 1.0,
            evidence=evidence,
        )
