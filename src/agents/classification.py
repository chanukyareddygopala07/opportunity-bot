"""Agent 04 — Classification Agent

Classifies opportunity type, field, education level, experience level, location type, funding type.

Keyword matching is word-boundary based: a bare "ai"/"cs" token must stand
alone ("ai research", "cs major") and never matches inside "email",
"chair" or "physics". Confidence reflects how many independent signals
matched rather than a hardcoded constant.
"""
import re

from src.agents.base import BaseAgent, AgentStatus, AgentCategory, AgentResult, AgentEvidence


def _contains_keyword(haystack: str, keyword: str) -> bool:
    """Word-boundary keyword match (multi-word keywords matched literally)."""
    pattern = r"(?<![\w])" + re.escape(keyword.lower()) + r"(?![\w])"
    return re.search(pattern, haystack) is not None


class ClassificationAgent(BaseAgent):
    AGENT_ID = "classification_agent"
    AGENT_NAME = "Classification Agent"
    AGENT_CATEGORY = AgentCategory.INTELLIGENCE
    AGENT_DESCRIPTION = "Classifies opportunity type, field, education level, and other attributes"

    FIELD_KEYWORDS = {
        # Ordered most-specific first; first hit with any keyword wins.
        "ai_ml": ["artificial intelligence", "machine learning", "deep learning", "neural network", "computer vision", "natural language processing", "nlp", "llm", "ml", "ai"],
        "computer_science": ["software engineering", "computer science", "backend", "frontend", "full stack", "full-stack", "swe", "software"],
        "data_science": ["data science", "data engineering", "data analysis", "analytics", "big data"],
        "robotics": ["robotics", "robot", "automation"],
        "cybersecurity": ["cybersecurity", "cyber security", "information security", "cryptography", "security"],
        "cloud": ["cloud computing", "aws", "azure", "devops"],
        "electronics": ["electronics", "embedded systems", "vlsi", "hardware", "iot"],
        "biotechnology": ["biotech", "biotechnology", "biology", "life sciences", "genomics"],
        "finance": ["quantitative finance", "quantitative", "trading", "fintech", "finance", "financial", "quant"],
        "design": ["product design", "ux design", "ux/ui", "user experience", "figma", "ux", "ui design"],
    }

    def process(self, input_data: dict) -> AgentResult:
        from src import schema

        opp = input_data.get("opportunity", {})
        text = f"{opp.get('title', '')} {opp.get('description', '')}".lower()

        opp_type = opp.get("type") or schema.infer_type(
            opp.get("title"), opp.get("description"), opp.get("category")
        )

        field, field_hits = self._classify_field(text)
        education_level = self._classify_education(text)
        experience_level = self._classify_experience(text)
        location_type = self._classify_location_type(opp)
        funding_type = self._classify_funding(opp)

        evidence = []
        if opp_type:
            evidence.append(AgentEvidence(
                field="opportunity_type", value=opp_type,
                confidence=0.8 if opp.get("type") else 0.6,
                agent_id=self.AGENT_ID,
            ))
        if field_hits:
            evidence.append(AgentEvidence(
                field="field", value=field,
                confidence=min(0.9, 0.5 + 0.2 * field_hits),
                agent_id=self.AGENT_ID,
            ))

        confidence = 0.3
        if opp_type and field != "other":
            confidence = 0.85
        elif opp_type or field != "other":
            confidence = 0.65

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
            confidence=confidence,
            evidence=evidence,
        )

    def _classify_field(self, text: str):
        """Returns (field, number_of_keyword_hits) — hits inform confidence."""
        for field_name, keywords in self.FIELD_KEYWORDS.items():
            hits = sum(1 for kw in keywords if _contains_keyword(text, kw))
            if hits:
                return field_name, hits
        return "other", 0

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
