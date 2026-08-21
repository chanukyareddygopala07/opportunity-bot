"""Agent 15 — User Support Agent

Answers questions about opportunities grounded in stored evidence.
Never invents information — returns what's in the database.
"""
from src.agents.base import BaseAgent, AgentStatus, AgentCategory, AgentResult, AgentEvidence


class UserSupportAgent(BaseAgent):
    AGENT_ID = "user_support_agent"
    AGENT_NAME = "User Support Agent"
    AGENT_CATEGORY = AgentCategory.USER
    AGENT_DESCRIPTION = "Answers questions about opportunities grounded in stored evidence"

    def process(self, input_data: dict) -> AgentResult:
        from src import db
        from src.deadlines import days_left, label, status

        question = input_data.get("question", "").lower()
        opportunity_id = input_data.get("opportunity_id")
        user_id = input_data.get("user_id")

        answer = "I don't have enough information to answer that question."
        confidence = 0.3

        if opportunity_id:
            opp = db.get_opportunity(opportunity_id)
            if opp:
                answer = self._answer_about_opportunity(question, opp, user_id)
                confidence = 0.8

        elif "eligible" in question or "eligibility" in question:
            answer = "Please provide an opportunity ID to check eligibility."
            confidence = 0.5

        elif "deadline" in question:
            answer = "Please provide an opportunity ID to check the deadline."
            confidence = 0.5

        evidence = [
            AgentEvidence(
                field="user_support_answer",
                value=answer[:200],
                confidence=confidence,
                agent_id=self.AGENT_ID,
            )
        ]

        return AgentResult(
            agent_id=self.AGENT_ID,
            status=AgentStatus.COMPLETED,
            data={
                "question": input_data.get("question", ""),
                "answer": answer,
                "opportunity_id": opportunity_id,
            },
            confidence=confidence,
            evidence=evidence,
        )

    def _answer_about_opportunity(self, question: str, opp: dict, user_id=None) -> str:
        from src.deadlines import days_left, label, status
        from src.trust import trust_label
        from src import db

        if "eligible" in question or "eligibility" in question:
            if user_id:
                profile = db.get_user_by_id(user_id)
                if profile:
                    from src.scoring import evaluate_eligibility
                    elig_status, reasons, missing = evaluate_eligibility(opp, profile)
                    parts = [f"Status: {elig_status}"]
                    parts.extend(reasons)
                    if missing:
                        parts.append(f"Missing: {', '.join(missing)}")
                    return "\n".join(parts)
            return f"Eligibility status: {opp.get('eligibility_status', 'unknown')}"

        if "deadline" in question:
            dl = opp.get("deadline")
            if dl:
                ds = status(opp)
                days = days_left(dl)
                return f"Deadline: {dl} ({label(ds)})" + (f" — {days} days left" if days is not None else "")
            return "No deadline recorded for this opportunity."

        if "stipend" in question or "salary" in question or "pay" in question:
            return f"Stipend: {opp.get('stipend') or 'Not specified'}"

        if "trust" in question or "verified" in question:
            return f"Trust score: {opp.get('trust_score', 'N/A')}/100 ({trust_label(opp.get('trust_score'))})"

        if "link" in question or "apply" in question:
            url = opp.get("application_url") or opp.get("official_url")
            return f"Application link: {url}" if url else "No application link available."

        return (
            f"{opp.get('title', 'Unknown')} at {opp.get('organization', 'Unknown')}\n"
            f"Type: {opp.get('type', 'Unknown')}\n"
            f"Location: {opp.get('location', 'Unknown')}\n"
            f"Deadline: {opp.get('deadline', 'Not specified')}\n"
            f"Trust: {opp.get('trust_score', 'N/A')}/100"
        )
