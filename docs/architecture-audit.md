# AAWARA Architecture Audit

## Existing System Summary

The current opportunity-bot is a Python/Flask application with:

- **Backend**: Flask web app + FastAPI REST API
- **Database**: SQLite (portable SQL, designed for PostgreSQL swap)
- **Frontend**: Jinja2 templates + vanilla CSS/JS
- **AI**: Multi-provider (Ollama local, Gemini, OpenAI) — advisory only
- **Discovery**: 2 scouts (fellowship_scout, internship_scout) with 40+ sources
- **Extraction**: Regex-based deterministic field extraction
- **Crawling**: HTTP fetcher with retries, rate limits, cooldowns
- **Verification**: Link checking + source trust scoring
- **Deduplication**: Exact (dedup_key) + near-duplicate (SequenceMatcher)
- **Eligibility**: Deterministic rule-based evaluation
- **Scoring**: Multi-component weighted scoring
- **Notifications**: Telegram bot with card-based interactions
- **Auth**: Session-based with OAuth (Google, GitHub)
- **Scheduling**: n8n webhook triggers pipeline

## What Already Exists (Reusable)

| Component | Location | Status |
|-----------|----------|--------|
| Discovery sources | src/discovery/ | Working — 40+ sources |
| Crawler fetcher | src/discovery/fetcher.py | Working — HTTP fetcher |
| Crawler router | src/discovery/router.py | Working — decides crawler type |
| Extraction | src/extraction/extractor.py | Working — regex patterns |
| Eligibility | src/scoring.py | Working — rule-based |
| Deduplication | src/dedupe.py | Working — near-duplicate detection |
| Verification | src/verification.py | Working — link checking |
| Trust scoring | src/trust.py | Working — deterministic 0-100 |
| Deadlines | src/deadlines.py | Working — timezone-aware |
| Schema | src/schema.py | Working — canonical opportunity shape |
| Database | src/db.py | Working — SQLite with migration |
| AI layer | src/ai.py | Working — multi-provider |
| Web app | src/webapp/ | Working — Flask + templates |
| API | src/api.py | Working — FastAPI REST |
| Worker | src/worker.py | Working — pipeline runner |
| Notifications | src/notifications/ | Working — Telegram |

## What Must Be Built

1. Agent base classes and interfaces
2. Agent orchestrator (task routing, dependencies, retries)
3. Agent task system (task tracking, status management)
4. Agent event system (event-driven communication)
5. 16 specialized agents (wrapping/extending existing modules)
6. Agent dashboard (real metrics from DB)
7. Admin dashboard enhancements
8. Evidence system (traceability)
9. Freshness monitoring
10. Change detection
11. User support agent
12. Application assistant
13. Natural language search agent

## Existing Gaps

- No formal agent abstraction (scouts are procedural)
- No task queue for agents (using crawl_jobs table)
- No event system (using execution_logs)
- No evidence tracking (data is stored but not traceable)
- No agent health monitoring
- No agent dashboard
- No change detection
- No formal recommendation system
- No natural language search
