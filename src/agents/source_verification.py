"""Agent 07 — Source Verification Agent

Verifies organization, domain, official source, opportunity existence, application URL.
Third-party sources must NEVER be marked official.
"""
from src.agents.base import BaseAgent, AgentStatus, AgentCategory, AgentResult, AgentEvidence

OFFICIAL_SOURCE_TYPES = ("official", "company", "government", "university", "official_university",
                          "official_company", "official_government", "official_institute",
                          "official_research_lab", "official_program")


class SourceVerificationAgent(BaseAgent):
    AGENT_ID = "source_verification_agent"
    AGENT_NAME = "Source Verification Agent"
    AGENT_CATEGORY = AgentCategory.QUALITY
    AGENT_DESCRIPTION = "Verifies organization, domain, official source, and opportunity existence"

    def process(self, input_data: dict) -> AgentResult:
        from src.verification import check_link
        from src import db

        opp = input_data.get("opportunity", {})
        source_type = (opp.get("source_type") or "").lower()
        is_official = any(t in source_type for t in OFFICIAL_SOURCE_TYPES)
        has_trust = (opp.get("organization_trust_score") or 0) >= 90

        check_url = opp.get("official_url") or opp.get("application_url") or opp.get("source_url")
        link_status = "unknown"
        link_message = "no URL to check"

        if check_url:
            try:
                link_status, link_message = check_link(check_url)
            except Exception as exc:
                link_status = "error"
                link_message = str(exc)[:200]

        verification_status = "unverified"
        if link_status == "live" and (is_official or has_trust):
            verification_status = "verified"
        elif link_status == "live":
            verification_status = "unverified"

        evidence = [
            AgentEvidence(
                field="source_verification",
                value=verification_status,
                source_url=check_url,
                confidence=0.9 if verification_status == "verified" else 0.5,
                agent_id=self.AGENT_ID,
            )
        ]

        return AgentResult(
            agent_id=self.AGENT_ID,
            status=AgentStatus.COMPLETED,
            data={
                "verification_status": verification_status,
                "official_source": is_official or has_trust,
                "link_status": link_status,
                "link_message": link_message,
                "source_type": source_type,
                "trust_score": opp.get("organization_trust_score"),
            },
            confidence=0.9 if verification_status == "verified" else 0.5,
            evidence=evidence,
        )
