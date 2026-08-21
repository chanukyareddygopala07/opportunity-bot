"""Agent 02 — Crawler Agent

Retrieves webpages safely and reliably using the appropriate crawler.
Uses the existing fetcher and router infrastructure.
"""
from src.agents.base import BaseAgent, AgentStatus, AgentCategory, AgentResult, AgentEvidence


class CrawlerAgent(BaseAgent):
    AGENT_ID = "crawler_agent"
    AGENT_NAME = "Crawler Agent"
    AGENT_CATEGORY = AgentCategory.DISCOVERY
    AGENT_DESCRIPTION = "Retrieves webpages safely and reliably using the appropriate crawler"

    def process(self, input_data: dict) -> AgentResult:
        from src.discovery import fetcher, router, entries
        from src import db

        sources = input_data.get("sources", [])
        run_id = input_data.get("run_id", "agent_run")
        pages = []
        crawled = 0
        errors = 0

        for source in sources:
            url = source.get("url")
            if not url:
                continue

            crawler_type = router.select_crawler(source)
            if crawler_type == router.RESPECT_ROBOTS:
                continue

            try:
                text, final_url, status = fetcher.fetch(
                    url, source=source
                )
                crawled += 1
                pages.append({
                    "url": url,
                    "final_url": final_url,
                    "status": status,
                    "content": text[:50000],
                    "crawler": crawler_type,
                    "source": source,
                })
            except Exception as exc:
                errors += 1
                db.record_filtering_decision(
                    run_id, source.get("id"), "crawl_error",
                    source.get("name", ""), source.get("organization", ""),
                    url, str(exc)[:200],
                )

        evidence = [
            AgentEvidence(
                field="pages_crawled",
                value=crawled,
                confidence=1.0,
                agent_id=self.AGENT_ID,
            )
        ]

        return AgentResult(
            agent_id=self.AGENT_ID,
            status=AgentStatus.COMPLETED,
            data={
                "pages": pages,
                "crawled": crawled,
                "errors": errors,
            },
            confidence=1.0 if errors == 0 else max(0.5, 1.0 - (errors / max(crawled + errors, 1))),
            evidence=evidence,
        )
