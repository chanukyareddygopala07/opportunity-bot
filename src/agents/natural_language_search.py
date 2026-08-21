"""Agent 12 — Natural Language Search Agent

Converts natural language queries into structured filters, then queries PostgreSQL.
"""
import re
from src.agents.base import BaseAgent, AgentStatus, AgentCategory, AgentResult, AgentEvidence


class NaturalLanguageSearchAgent(BaseAgent):
    AGENT_ID = "natural_language_search_agent"
    AGENT_NAME = "Natural Language Search Agent"
    AGENT_CATEGORY = AgentCategory.USER
    AGENT_DESCRIPTION = "Converts natural language queries into structured opportunity filters"

    COUNTRY_PATTERNS = {
        "india": ["India"], "usa": ["USA"], "us": ["USA"],
        "uk": ["UK"], "germany": ["Germany"], "canada": ["Canada"],
        "australia": ["Australia"], "europe": ["Europe"],
        "international": ["International"],
    }

    TYPE_PATTERNS = {
        "internship": ["internship"], "intern": ["internship"],
        "fellowship": ["fellowship"], "fellow": ["fellowship"],
        "scholarship": ["scholarship"],
        "research": ["research_program"],
        "hackathon": ["hackathon"],
        "job": ["job"], "jobs": ["job"],
        "summer": ["summer_program"],
        "grant": ["grant"],
    }

    FIELD_PATTERNS = {
        "ai": ["ai_ml"], "ml": ["ai_ml"], "artificial intelligence": ["ai_ml"],
        "machine learning": ["ai_ml"], "computer science": ["computer_science"],
        "data science": ["data_science"], "robotics": ["robotics"],
        "finance": ["finance"], "design": ["design"],
    }

    FUNDING_PATTERNS = {
        "fully funded": ["fully_funded"], "paid": ["paid"],
        "unpaid": ["unpaid"], "stipend": ["paid"],
    }

    def process(self, input_data: dict) -> AgentResult:
        from src import db

        query = input_data.get("query", "")
        filters = self._parse_query(query)

        opportunities = db.list_opportunities()
        filtered = self._apply_filters(opportunities, filters)

        evidence = [
            AgentEvidence(
                field="search_results",
                value=len(filtered),
                confidence=0.8,
                agent_id=self.AGENT_ID,
            )
        ]

        return AgentResult(
            agent_id=self.AGENT_ID,
            status=AgentStatus.COMPLETED,
            data={
                "query": query,
                "filters": filters,
                "results": filtered[:20],
                "total_matches": len(filtered),
            },
            confidence=0.8,
            evidence=evidence,
        )

    def _parse_query(self, query: str) -> dict:
        query_lower = query.lower()
        filters = {}

        countries = []
        for pattern, values in self.COUNTRY_PATTERNS.items():
            if pattern in query_lower:
                countries.extend(values)
        if countries:
            filters["country"] = list(set(countries))

        types = []
        for pattern, values in self.TYPE_PATTERNS.items():
            if pattern in query_lower:
                types.extend(values)
        if types:
            filters["type"] = list(set(types))

        fields = []
        for pattern, values in self.FIELD_PATTERNS.items():
            if pattern in query_lower:
                fields.extend(values)
        if fields:
            filters["field"] = list(set(fields))

        funding = []
        for pattern, values in self.FUNDING_PATTERNS.items():
            if pattern in query_lower:
                funding.extend(values)
        if funding:
            filters["funding"] = list(set(funding))

        year_match = re.search(r"(\d)(?:st|nd|rd|th)\s*year", query_lower)
        if year_match:
            filters["year"] = [int(year_match.group(1))]

        if "remote" in query_lower:
            filters["remote"] = True

        return filters

    def _apply_filters(self, opportunities: list, filters: dict) -> list:
        results = []
        for opp in opportunities:
            match = True

            if "country" in filters:
                opp_country = (opp.get("country") or "").lower()
                if not any(c.lower() in opp_country for c in filters["country"]):
                    match = False

            if "type" in filters:
                opp_type = (opp.get("type") or "").lower()
                if not any(t.lower() in opp_type for t in filters["type"]):
                    match = False

            if "remote" in filters and filters["remote"]:
                if not opp.get("remote"):
                    location = (opp.get("location") or "").lower()
                    if "remote" not in location:
                        match = False

            if match:
                results.append(opp)

        return results
