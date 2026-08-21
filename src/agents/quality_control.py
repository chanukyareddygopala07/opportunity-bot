"""Agent 09 — Quality Control Agent

Every opportunity must pass through QC before publication.
Validates title, organization, source, URL, type, deadline, eligibility, etc.
"""
from src.agents.base import BaseAgent, AgentStatus, AgentCategory, AgentResult, AgentEvidence


class QualityControlAgent(BaseAgent):
    AGENT_ID = "quality_control_agent"
    AGENT_NAME = "Quality Control Agent"
    AGENT_CATEGORY = AgentCategory.QUALITY
    AGENT_DESCRIPTION = "Validates opportunity data quality before publication"

    def process(self, input_data: dict) -> AgentResult:
        from src import schema

        opp = input_data.get("opportunity", {})
        classification = input_data.get("classification", {})
        eligibility = input_data.get("eligibility", {})
        deadline = input_data.get("deadline", {})
        verification = input_data.get("verification", {})
        duplicate = input_data.get("duplicate", {})

        checks = {}
        issues = []

        # Title check
        checks["title"] = bool(opp.get("title"))
        if not checks["title"]:
            issues.append("missing title")

        # Organization check
        checks["organization"] = bool(opp.get("organization"))
        if not checks["organization"]:
            issues.append("missing organization")

        # Source URL check
        checks["source_url"] = bool(
            opp.get("application_url") or opp.get("official_url") or opp.get("source_url")
        )
        if not checks["source_url"]:
            issues.append("no application/official/source URL")

        # Type check
        opp_type = classification.get("opportunity_type") or opp.get("type")
        checks["opportunity_type"] = opp_type in schema.OPPORTUNITY_TYPES if opp_type else False
        if not checks["opportunity_type"]:
            issues.append("invalid or missing opportunity type")

        # Deadline check
        deadline_status = deadline.get("deadline_status", "UNKNOWN")
        checks["deadline"] = deadline_status in ("OPEN", "CLOSING_SOON", "NO_DEADLINE")
        if not checks["deadline"] and deadline_status == "UNKNOWN":
            issues.append("deadline unparseable")

        # Eligibility check
        elig_status = eligibility.get("eligibility_status", "unknown")
        checks["eligibility"] = elig_status != "not_eligible"
        if not checks["eligibility"]:
            issues.append("marked not_eligible")

        # Duplicate check
        checks["not_duplicate"] = not duplicate.get("is_duplicate", False)
        if not checks["not_duplicate"]:
            issues.append("duplicate detected")

        # Verification check
        checks["verification"] = verification.get("verification_status") in ("verified", "unverified")

        passed = all(checks.values())
        review_needed = (
            elig_status == "unclear"
            or deadline_status == "UNKNOWN"
            or not checks["source_url"]
        )

        if not passed and not review_needed:
            qc_status = "FAIL"
        elif review_needed:
            qc_status = "REVIEW_REQUIRED"
        else:
            qc_status = "PASS"

        evidence = [
            AgentEvidence(
                field="qc_status",
                value=qc_status,
                confidence=1.0 if qc_status == "PASS" else 0.5,
                agent_id=self.AGENT_ID,
            )
        ]

        return AgentResult(
            agent_id=self.AGENT_ID,
            status=AgentStatus.COMPLETED,
            data={
                "qc_status": qc_status,
                "checks": checks,
                "issues": issues,
            },
            confidence=1.0 if qc_status == "PASS" else 0.5,
            evidence=evidence,
        )
