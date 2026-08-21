"""Agent 03 — Extraction Agent

Converts raw webpage content into structured opportunity data.
Uses the existing regex-based extractor. Never guesses — returns UNKNOWN for missing fields.
"""
from src.agents.base import BaseAgent, AgentStatus, AgentCategory, AgentResult, AgentEvidence


class ExtractionAgent(BaseAgent):
    AGENT_ID = "extraction_agent"
    AGENT_NAME = "Extraction Agent"
    AGENT_CATEGORY = AgentCategory.INTELLIGENCE
    AGENT_DESCRIPTION = "Converts raw webpage content into structured opportunity data"

    def process(self, input_data: dict) -> AgentResult:
        from src.extraction.extractor import extract_fields
        from src import schema

        pages = input_data.get("pages", [])
        extracted = []

        for page in pages:
            content = page.get("content", "")
            source = page.get("source", {})

            fields = extract_fields(content)

            opportunity = {
                "title": self._extract_title(content, source),
                "organization": source.get("organization", ""),
                "description": content[:2000],
                "source_url": page.get("url", ""),
                "application_url": fields.get("application_url"),
                "official_url": source.get("url", ""),
                "source_type": source.get("type", "unknown"),
                "location": self._extract_location(content),
                "country": self._extract_country(content),
                "remote": "remote" in content.lower()[:5000],
                "deadline": fields.get("deadline"),
                "duration": fields.get("duration"),
                "stipend": fields.get("stipend"),
                "currency": fields.get("currency"),
                "funding": fields.get("funding"),
                "minimum_gpa": fields.get("minimum_gpa"),
                "eligible_degrees": fields.get("eligible_degrees"),
                "eligible_years": fields.get("eligible_years"),
                "eligible_branches": fields.get("eligible_branches"),
                "eligible_countries": fields.get("eligible_countries"),
                "preferred_skills": fields.get("preferred_skills"),
            }

            opportunity = schema.normalize_opportunity(opportunity)
            extracted.append(opportunity)

        valid = [e for e in extracted if e.get("title")]
        evidence = [
            AgentEvidence(
                field="records_extracted",
                value=len(valid),
                confidence=1.0,
                agent_id=self.AGENT_ID,
            )
        ]

        return AgentResult(
            agent_id=self.AGENT_ID,
            status=AgentStatus.COMPLETED,
            data={
                "opportunities": extracted,
                "total": len(extracted),
                "valid": len(valid),
            },
            confidence=1.0 if valid else 0.0,
            evidence=evidence,
        )

    def _extract_title(self, content: str, source: dict) -> str:
        import re
        title_match = re.search(r"<title[^>]*>([^<]+)</title>", content, re.IGNORECASE)
        if title_match:
            return title_match.group(1).strip()[:200]
        h1_match = re.search(r"<h1[^>]*>([^<]+)</h1>", content, re.IGNORECASE)
        if h1_match:
            return h1_match.group(1).strip()[:200]
        return source.get("name", "")[:200] or None

    def _extract_location(self, content: str) -> str:
        import re
        location_patterns = [
            r"(?:location|place|based in|located in)[:\s]*([^\n<]{3,80})",
            r"(Bangalore|Bengaluru|Mumbai|Delhi|Hyderabad|Chennai|Pune|Remote|India|USA|UK)",
        ]
        for pattern in location_patterns:
            match = re.search(pattern, content[:10000], re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _extract_country(self, content: str) -> str:
        import re
        text = content[:10000].lower()
        if "india" in text or "indian" in text:
            return "India"
        if "united states" in text or " usa " in text or "us citizen" in text:
            return "USA"
        if "united kingdom" in text or " uk " in text:
            return "UK"
        return None
