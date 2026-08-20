# AAWARA — Target Architecture

Design goals: reliability, data accuracy, source verification, security,
performance, simplicity, user experience. Free-first: no paid APIs unless
optional and behind an abstraction.

## 1. High-level view

```
Browser / Mobile
      │
      ▼
AAWARA Frontend  (kept: Flask + Jinja on :8080 during transition;
                  optional future: Next.js/TS/Tailwind/shadcn)
      │  REST APIs
      ▼
FastAPI  (new, :8000)  — public API + admin API (JWT/scoped keys)
      │
      ▼
Opportunity Intelligence Layer (Python)
  ├─ NL query → structured filters        (AI optional, rule fallback)
  ├─ AI matching / recommendations        (AI optional, deterministic fallback)
  ├─ Deadline Engine                      (deterministic, timezone-aware)
  ├─ Trust Score                          (deterministic)
  └─ Verification pipeline                (deterministic + AI-assisted)
      │
      ▼
Crawler Router → Crawlee / Crawl4AI / Firecrawl(self-hosted) /
                 Playwright / Browser Use   (records crawler_used)
      │
      ▼
Raw content → Extraction Engine → Validation → Official-source priority
→ Deduplication (canonical) → AI classification → PostgreSQL
      │
      ▼
PostgreSQL (new, :5432)  +  Redis (new, :6379: queue/cache)
      │
      ▼
AAWARA UI / notifications / admin
```

## 2. Service topology (docker compose)

| Service | Port | Role |
|---|---|---|
| web (Flask UI) | 8080 (keep) | current UI until frontend phase |
| api (FastAPI) | 8000 | REST API + admin API |
| postgres | 5432 | primary store |
| redis | 6379 | crawl job queue, cache |
| crawler worker | — | consumes job queue, runs router |
| n8n | 5678 | scheduling (cron) → enqueue jobs |
| ollama | 11434 | optional local AI |

Transition rule: the Flask app stays runnable end-to-end at every phase
(no big-bang cutover). SQLite stays as the file DB during migration; a
`--pg` mode migrates when PostgreSQL lands.

## 3. Data model (PostgreSQL)

- `opportunities`: id, title, organization, organization_type, description,
  opportunity_type, category, subcategory, country, state, city, location,
  remote, hybrid, start_date, end_date, deadline, application_url,
  official_url, source_url, source_domain, eligibility (jsonb),
  eligible_countries (text[]), eligible_degrees (text[]), eligible_years
  (int[]), eligible_branches (text[]), minimum_age, maximum_age,
  experience_required, skills (text[]), fields (text[]), stipend, salary,
  funding, currency, duration, application_fee, housing, travel_support,
  certificate, status (OPEN/CLOSING_SOON/CLOSED/UNKNOWN/NO_DEADLINE),
  verification_status, trust_score, relevance_score, last_crawled,
  last_verified, next_verification, created_at, updated_at.
- `sources` (registry): name, domain, source_type, country,
  organization_type, crawl_frequency, last_crawled, last_success,
  last_failure, status, priority, crawler preference, robots policy.
- `crawl_jobs`: job_id, source, url, crawler, priority, status
  (QUEUED/RUNNING/COMPLETED/FAILED/RETRYING/CANCELLED), started_at,
  completed_at, retry_count, error, items_found/updated/created,
  duplicates_found.
- `opportunity_sources` (alt URLs on canonical), `reports`,
  `verifications`, `trust_scores`, `deadlines`, `users`, `student_profiles`,
  `saved_opportunities` (+ collections), `applications`, `notifications`,
  `search_logs`, `admin_audit_log`.
- Full-text search: PostgreSQL tsvector; semantic search later (pgvector)
  behind an abstraction with keyword fallback.

## 4. Crawler router

Input: source URL. Decision inputs: robots.txt, page type (static/AI-friendly/
JS-heavy/interactive), extraction complexity, site health. Output: crawler
name recorded per run (`crawler_used`). All crawlers run in-process workers
with per-source rate limits, concurrency caps, timeouts, retries with
exponential backoff, and circuit breakers. Priority queue: deadline≤7d /
frequently-changing / new / reported → high; ≤30d → medium; evergreen → low.

## 5. Verification & no-hallucination

Pipeline: raw source → structured extraction → validation → official-source
verification → deadline verification → eligibility verification → duplicate
detection → trust score → DB. UNKNOWN/null preferred over fabrication.
AI never writes facts; it only assists classification/reasoning with
deterministic validation.

## 6. APIs (FastAPI)

- Public: GET /opportunities, GET /opportunities/{id},
  POST /opportunities/search (NL), POST /opportunities/match,
  GET /categories, GET /sources, GET /stats, GET /recommendations,
  POST /saved, GET /saved, POST /applications, GET /applications,
  POST /crawl, GET /crawl/jobs, POST /report, GET /health.
- Admin: auth + authorization (API keys/roles), full CRUD over
  opportunities/sources/jobs/users.

## 7. AI provider abstraction

`AIProvider` interface with `OllamaProvider`, `OpenAIProvider`,
`GeminiProvider`; deterministic fallbacks everywhere (keyword search,
rule-based classification, manual deadline rules). System keeps working with
AI down.

## 8. Frontend strategy

Phase 1 (this sprint): redesign the existing Flask UI to the neon-green
editorial design system (brief "Design and build AAWARA website") — zero
rebuild risk, keeps :8080. Later, optional Next.js migration is additive,
not a replacement, gated on real need.

## 9. Observability & security

Structured JSON logs; metrics: crawl duration/failures, AI failures, API
failures, queue depth, items created/updated, duplicates, verification
failures, source health. Secrets only via env/.env (gitignored); input
validation, parameterized SQL, CSRF on state-changing forms, rate limiting,
authn/authz, no secret exposure (tested by CI audit step).

## 10. Ports & infra summary

8080 UI · 8000 API · 5432 Postgres · 6379 Redis · 5678 n8n · 11434 Ollama.
Everything self-hosted; docker compose up documented in LOCAL-DEVELOPMENT.md.