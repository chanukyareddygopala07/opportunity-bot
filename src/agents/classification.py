"""Agent 04 — Classification Agent

Classifies opportunity type, field, education level, experience level, location type, funding type.
"""
from src.agents.base import BaseAgent, AgentStatus, AgentCategory, AgentResult, AgentEvidence


class ClassificationAgent(BaseAgent):
    AGENT_ID = "classification_agent"
    AGENT_NAME = "Classification Agent"
    AGENT_CATEGORY = AgentCategory.INTELLIGENCE
    AGENT_DESCRIPTION = "Classifies opportunity type, field, education level, and other attributes"

    FIELD_KEYWORDS = {
        "ai_ml": ["artificial intelligence", "machine learning", "ml", "ai", "deep learning", "nlp", "llm"],
        "computer_science": ["software engineering", "computer science", "swe", "cs", "backend", "frontend"],
        "data_science": ["data science", "data engineering", "analytics", "data analysis"],
        "robotics": ["robotics", "robot", "automation"],
        "electronics": ["electronics", "embedded", "vlsi", "hardware"],
        "biotechnology": ["biotech", "biology", "life sciences", "genomics"],
        "finance": ["finance", "quantitative", "quant", "trading", "financial"],
        "design": ["design", "ux", "ui", "figma"],
    }

    def process(self, input_data: dict) -> AgentResult:
        from src import schema

        opp = input_data.get("opportunity", {})
        text = f"{opp.get('title', '')} {opp.get('description', '')}".lower()

        opp_type = opp.get("type") or schema.infer_type(
            opp.get("title"), opp.get("description"), opp.get("category")
        )

        field = self._classify_field(text)
        education_level = self._classify_education(text)
        experience_level = self._classify_experience(text)
        location_type = self._classify_location_type(opp)
        funding_type = self._classify_funding(opp)

        evidence = []
        if opp_type:
            evidence.append(AgentEvidence(
                field="opportunity_type", value=opp_type,
                confidence=0.8, agent_id=self.AGENT_ID,
            ))

        return AgentResult(
            agent_id=self.AGENT_ID,
            status=AgentStatus.COMPLETED,
            data={
                "opportunity_type": opp_type,
                "field": field,
                "education_level": education_level,
                "experience_level": experience_level,
                "location_type": location_type,
                "funding_type": funding_type,
            },
            confidence=0.8 if opp_type else 0.3,
            evidence=evidence,
        )

    def _classify_field(self, text: str) -> str:
        for field, keywords in self.FIELD_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    return field
        return "other"

    def _classify_education(self, text: str) -> str:
        if any(w in text for w in ["ph.d", "phd", "doctoral", "postdoctoral"]):
            return "doctoral"
        if any(w in text for w in ["master", "m.tech", "m.sc", "mba", "postgraduate"]):
            return "postgraduate"
        if any(w in text for w in ["bachelor", "b.tech", "b.e", "undergraduate", "b.sc"]):
            return "undergraduate"
        return "unknown"

    def _classify_experience(self, text: str) -> str:
        if any(w in text for w in ["senior", "lead", "principal", "5+ years", "7+ years"]):
            return "experienced"
        if any(w in text for w in ["junior", "entry level", "fresher", "0-2 years"]):
            return "entry_level"
        if any(w in text for w in ["intern", "internship", "student", "training"]):
            return "intern"
        return "unknown"

    def _classify_location_type(self, opp: dict) -> str:
        if opp.get("remote"):
            return "remote"
        if opp.get("hybrid"):
            return "hybrid"
        location = (opp.get("location") or "").lower()
        if "remote" in location:
            return "remote"
        if "hybrid" in location:
            return "hybrid"
        return "onsite"

    def _classify_funding(self, opp: dict) -> str:
        funding = (opp.get("funding") or "").lower()
        if "fully funded" in funding:
            return "fully_funded"
        if "paid" in funding or opp.get("stipend"):
            return "paid"
        if "unpaid" in funding:
            return "unpaid"
        return "unknown"
