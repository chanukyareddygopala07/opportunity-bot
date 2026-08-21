"""Agent 13 — Freshness Agent

Tracks and monitors opportunity freshness: last_crawled, last_verified, next_verification.
Prioritizes deadlines approaching within 7 days, then 30 days.
"""
from src.agents.base import BaseAgent, AgentStatus, AgentCategory, AgentResult, AgentEvidence


class FreshnessAgent(BaseAgent):
    AGENT_ID = "freshness_agent"
    AGENT_NAME = "Freshness Agent"
    AGENT_CATEGORY = AgentCategory.QUALITY
    AGENT_DESCRIPTION = "Tracks and monitors opportunity freshness and staleness"

    def process(self, input_data: dict) -> AgentResult:
        from src import db
        from src.deadlines import days_left, status
        from datetime import datetime, timezone

        opportunities = db.list_opportunities(exclude_duplicates=False)
        now = datetime.now(timezone.utc)

        fresh = 0
        stale = 0
        urgent = 0
        needs_verification = []

        for opp in opportunities:
            last_seen = opp.get("last_seen")
            is_fresh = False

            if last_seen:
                try:
                    seen_dt = datetime.fromisoformat(str(last_seen).strip())
                    days_since = (now - seen_dt).days
                    is_fresh = days_since <= 14
                except (ValueError, TypeError):
                    pass

            if is_fresh:
                fresh += 1
            else:
                stale += 1

            deadline_days = days_left(opp.get("deadline"))
            if deadline_days is not None and 0 <= deadline_days <= 7:
                urgent += 1

            next_verification = opp.get("next_verification")
            if next_verification:
                try:
                    nv_dt = datetime.fromisoformat(str(next_verification).strip())
                    if nv_dt <= now:
                        needs_verification.append(opp["id"])
                except (ValueError, TypeError):
                    needs_verification.append(opp["id"])

        evidence = [
            AgentEvidence(
                field="fresh_opportunities",
                value=fresh,
                confidence=1.0,
                agent_id=self.AGENT_ID,
            )
        ]

        return AgentResult(
            agent_id=self.AGENT_ID,
            status=AgentStatus.COMPLETED,
            data={
                "total": len(opportunities),
                "fresh": fresh,
                "stale": stale,
                "urgent_deadline": urgent,
                "needs_verification": len(needs_verification),
                "needs_verification_ids": needs_verification[:20],
            },
            confidence=1.0,
            evidence=evidence,
        )
