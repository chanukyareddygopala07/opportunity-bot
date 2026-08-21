"""Agent 11 — Recommendation Agent

Matches opportunities against student profiles.
Do NOT recommend solely based on title similarity — actual eligibility matters.
"""
from src.agents.base import BaseAgent, AgentStatus, AgentCategory, AgentResult, AgentEvidence


class RecommendationAgent(BaseAgent):
    AGENT_ID = "recommendation_agent"
    AGENT_NAME = "Recommendation Agent"
    AGENT_CATEGORY = AgentCategory.USER
    AGENT_DESCRIPTION = "Matches opportunities against student profiles with explainable scores"

    def process(self, input_data: dict) -> AgentResult:
        from src.scoring import score_opportunity, evaluate_eligibility, score_breakdown

        opp = input_data.get("opportunity", {})
        profile = input_data.get("profile") or input_data.get("student_profile")

        if not profile:
            return AgentResult(
                agent_id=self.AGENT_ID,
                status=AgentStatus.COMPLETED,
                data={
                    "match_score": None,
                    "status": "unknown",
                    "reasons": ["no student profile"],
                    "missing": ["student_profile"],
                },
                confidence=0.0,
            )

        breakdown = score_breakdown(opp, profile)
        score = breakdown.get("overall")
        status = breakdown.get("status", "unknown")
        reasons = breakdown.get("reasons", [])
        missing = breakdown.get("missing", [])
        parts = breakdown.get("parts", {})

        reasons_text = []
        for r in reasons:
            reasons_text.append(f"{'+' if 'met' in r or 'eligible' in r or 'open' in r else '?'} {r}")
        for m in missing:
            reasons_text.append(f"o {m}")

        evidence = [
            AgentEvidence(
                field="match_score",
                value=score,
                confidence=0.8 if score else 0.0,
                agent_id=self.AGENT_ID,
            )
        ]

        return AgentResult(
            agent_id=self.AGENT_ID,
            status=AgentStatus.COMPLETED,
            data={
                "match_score": score,
                "eligibility_status": status,
                "reasons": reasons_text,
                "missing_information": missing,
                "component_scores": parts,
                "eligibility_pct": breakdown.get("eligibility_pct", 0),
                "career_fit": breakdown.get("career_fit"),
            },
            confidence=0.8 if score else 0.0,
            evidence=evidence,
        )
