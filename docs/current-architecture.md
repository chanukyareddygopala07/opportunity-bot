# AAWARA — Current Architecture (Audit)

Date: 2026-08-20
Status: living document — update as the platform evolves.

## 1. Overview

AAWARA is currently a **single-process Flask application** that combines:

- Web UI (Flask + Jinja2 templates)
- Opportunity discovery pipeline (scouts/crawlers)
- SQLite persistence
- Optional AI layer (Ollama / OpenAI / Gemini)
- Telegram bot (legacy)
- Scheduling via n8n (Docker)

The entire system runs as a handful of Python modules against one SQLite
database. There is no separate frontend, no API layer, no queue, no
PostgreSQL.

## 2. Runtime topology

```
n8n (Docker, port 5678)
  └─ cron workflow (every 2h)
       └─ POST /run  (X-Run-Token header)
            └─ Flask app (port 8080) = web UI + pipeline in one process
                 ├─ src/webapp/*      — routes, auth, templates
                 ├─ src/discovery/*   — scouts (Arjun, Vidya), ATS fetchers
                 ├─ src/worker.py     — pipeline orchestration
                 ├─ src/verification.py
                 ├─ src/dedupe.py
                 ├─ src/scoring.py    — eligibility engine
                 ├─ src/ai.py         — Rudra + advisory assessments
                 └─ SQLite: data/opportunity.db
```

Docker Compose services (docker-compose.yml):
- `n8n` — scheduler, port 5678
- `web` — the Flask app (python image), port 8080
- (Ollama optional — `host.docker.internal:11434`)

## 3. Frontend

- **Framework:** Flask server-rendered Jinja2 templates. No JS framework.
- **Templates** (src/webapp/templates/): base, index, list, detail, saved,
  top, urgent, stats, review, profile, register, login, oauth, resources,
  rudra, resume, tailor, autofill, applications, 404, _items partial.
- **Styling:** single static/style.css, dark theme, CSS custom properties
  (--accent #5b8cff, --saffron, --bg #0d1117, etc.).
- **JS:** vanilla — Rudra streaming chat (fetch + SSE reader), service
  worker registration, no build step, no bundler.
- **PWA:** manifest.json + minimal sw.js served by Flask routes.
- **Responsive:** media queries; mobile nav is a wrapping pill bar.

## 4. Backend

- **Framework:** Flask 3.0.3 (src/webapp/__init__.py, views.py).
- **Routes (37):** /, /opportunities, /internships, /fellowships, /review,
  /top, /urgent, /saved, /o/<id>, save/unsave, /stats, /profile,
  /register, /login, /logout, OAuth (Google, GitHub), /rudra (+/send,
  /stream, /clear), /resume (+/download, /tailor), /applications (+status,
  /delete), /api/autofill/token, /api/autofill/resume, /run (pipeline hook),
  /health, /stats.json, /manifest.json, /sw.js, /resources.
- **Auth:** session cookies (tokens table); scrypt password hashing;
  Google/GitHub OAuth via src/webapp/oauth.py; per-user API token for the
  autofill extension (hashed, Bearer header).
- **Services:** helpers (scoring, filtering, pagination), auth, oauth.

## 5. Database (SQLite)

- Path: `data/opportunity.db` (DATABASE_PATH env override; migrations in
  `src/db.py::_migrate`).
- 21 tables: users, sessions, bookmarks, applications, opportunities,
  sources, opportunity_sources, eligibility_results, scores, notifications,
  deadlines, execution_logs, duplicates, verifications, search_queries,
  system_errors, ai_assessments, discovery_runs, source_health,
  filtering_decisions, raw_responses, chat_messages.
- Opportunity columns: id, dedup_key, title, organization, type, category,
  description, country, location, remote, hybrid, deadline, apply_url,
  official_url, source_url, source_domain, requirements, preferred_skills,
  funding, stipend, eligibility_status, match_score, first_seen, listed_at,
  status, saved, last_seen, duplicate_of, created_at, updated_at.

## 6. Discovery / Crawling

- **Scouts:** `src/discovery/internship_scout.py` (Arjun),
  `fellowship_scout.py` (Vidya), routed by source config.
- **Fetching:** `fetcher.py` — urllib + requests-style fetches, robots.txt
  respect, rate limiting (rate_limit_ms), timeouts, retries, exponential
  backoff, cooldown, circuit breaker per source (source_health table).
- **ATS adapters:** `ats.py` — Greenhouse, Ashby, Lever, generic JSON.
- **Parsers:** `parsers.py`, `src/extraction/extractor.py` (regex-based),
  `src/extraction/pdf.py` (pypdf link extraction).
- **Gating:** role_patterns, location_filter, include/exclude patterns,
  pattern_gate, role_gate, location_gate (per source).
- **Observability:** every run logged to `discovery_runs` (scout, source,
  raw_items, gates, stored_new, duplicates, eligible counts, error,
  http_status, response_ms).
- **Sources:** 50 in config/sources.json, 36 enabled; curated_links.json
  (4 groups of official portals).

## 7. Verification / Deduplication / Scoring

- `src/verification.py`: link checks (HTTP status), deadline checks,
  verification records; AI assessment records (advisory only).
- `src/dedupe.py`: normalized title + org + URL similarity.
- `src/scoring.py`: eligibility engine v2 (CGPA parse, citizenship/REU
  nuance, score breakdown: eligibility% + career fit + overall), match
  score stored per user.
- `src/eligibility/` — rule-based eligibility modules.

## 8. AI

- `src/ai.py`:
  - Providers: OpenAI (`_openai_chat`), Gemini (`_gemini_chat`,
    `gemini_stream`), local Ollama (is_available/chat). Fallback order:
    OpenAI → Gemini → Ollama → None.
  - Rudra chat (career guide, advisory-only, guardrails in
    RUDRA_SYSTEM_PROMPT) with SSE streaming endpoint.
  - Assessment pipeline (assess/assess_new) — strict JSON, unknown-over-
    guess policy.
- **Policy:** AI is advisory; never overwrites rule-based fields.

## 9. Resume + Autofill

- `src/resume.py`: fact-locked resume builder, JD-aware tailoring
  (reorder-only), .txt/.pdf export (reportlab).
- Chrome MV3 extension (`extension/`): background fetch of
  /api/autofill/resume with Bearer token; content script fills empty
  fields only.

## 10. Infrastructure

- docker-compose.yml (n8n + web), .env (gitignored), .env.example.
- SQLite file DB; no PostgreSQL/Redis.
- Logging: python logging + execution_logs + system_errors tables.
- Tests: pytest, 356 passing (tests/).

## 11. Ports

- Frontend/whole app: 8080 (keep).
- n8n: 5678. Ollama: 11434 (optional).

## 12. Key files

| File | Role |
|---|---|
| src/webapp/views.py | all routes |
| src/db.py | schema + data access |
| src/discovery/* | crawlers |
| src/worker.py | pipeline |
| src/scoring.py | eligibility/matching |
| src/ai.py | AI providers + Rudra |
| config/sources.json | source registry |
| data/opportunity.db | SQLite database |