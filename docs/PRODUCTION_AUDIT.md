# AAWARA Production Audit

**Date:** 2026-08-24
**Scope:** full repository audit performed before any remediation work.
**Baseline test status:** 461 passed / 4 failed (all 4 failures are time-bomb tests in `tests/test_deadlines.py` that hardcode calendar dates).

---

## 1. Current architecture

AAWARA today is a **single-process, SQLite-backed opportunity aggregator** with a server-rendered Flask web app, a small FastAPI JSON API, an n8n-scheduled pipeline, and an optional local/remote LLM layer ("Rudra" chat + advisory eligibility assessment).

```text
n8n cron (08:00 / 18:00 IST)
   │  POST /run  (X-Run-Token)
   ▼
stdlib webhook (src/webhook.py) ──► src/worker.run_pipeline()
   │                                   ├─ enqueue_from_sources (crawl_jobs rows)
   │                                   ├─ fellowship_scout + internship_scout
   │                                   ├─ queue settle
   │                                   ├─ verification.verify_due(20)
   │                                   ├─ notifier (Telegram; disabled by default)
   │                                   ├─ ai.assess_new (Ollama only, advisory)
   │                                   └─ maintenance
   ▼
SQLite  data/opportunity.db  (30+ tables, FTS5)
   ▲
Flask webapp :8080 (src/webapp) — browse/search/detail/auth/OAuth/Rudra/resume/admin
FastAPI API    (src/api.py)     — JSON read endpoints + crawl trigger + agent introspection
```

### Technology stack

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.13 | stdlib-first discipline |
| Web UI | Flask 3.0 + Jinja2 | dev server (`app.run`) |
| API | FastAPI (+uvicorn/pydantic) | **missing from requirements.txt** |
| DB | SQLite single file | shared by 3 containers over volume mount |
| Scheduling | self-hosted n8n | POSTs `/run` twice daily |
| Crawling | stdlib urllib fetcher + Greenhouse/Ashby/Lever JSON APIs + RSS + PDF (pypdf) | no headless browser |
| AI | OpenAI → Gemini → Ollama via raw `urllib` | no SDK, no gateway abstraction |
| Tests | pytest, 41 files, ~465 tests | real DB fixtures, targeted network mocks |

---

## 2. Existing functionality (working and worth preserving)

The deterministic core is genuinely well built and honest-by-design:

- **Ingestion**: config-driven source registry (50 sources), ATS JSON adapters, pagination, role/location/pattern gates, per-stage counters (`discovery_runs`, `filtering_decisions`).
- **Idempotent upserts**: unique `dedup_key`, `ON CONFLICT DO UPDATE`.
- **Deterministic extraction**: regex deadline/stipend/GPA/degree/branch/country/skills extraction — nothing invented.
- **Dedup**: exact key + near-duplicate similarity ≥0.85 (SequenceMatcher + Jaccard), canonical selection by oldest first-seen, source-link transfer, duplicates never deleted.
- **Eligibility policy**: deterministic rules; hard exclusions only when explicitly stated; missing info never disqualifies; status score caps; explainable reasons.
- **Scoring**: confidence-weighted transparent breakdown per user.
- **Verification lifecycle**: link-live checks, official-source-first rule, corroboration ≥2 sources, scheduled re-check cadence (12h/24h/weekly), history table.
- **Trust score**: composite 0–100 with recorded components.
- **Deadline engine**: OPEN/CLOSING_SOON/CLOSED/UNKNOWN with IST timezone.
- **Webapp**: search (FTS5), filters, detail pages, accounts (scrypt passwords, DB sessions), Google/GitHub OAuth with state validation, bookmarks, application tracker, resume builder/tailor (no AI), in-app notifications, recently-viewed, admin dashboard, PWA manifest, robots/sitemap.
- **Tests**: meaningful behavioral assertions against a real temp DB.

**These must not be rewritten. They are the product's spine.**

---

## 3. Critical findings

### 3.1 Security (P0)

| # | Severity | Finding | Location |
|---|---|---|---|
| S1 | **Critical** | Admin gate = `username == "admin"` env-default string compare; registration does not reserve the name → anyone can register `admin` and gain full admin | `src/webapp/views.py:67-75`, registration `views.py:727-764` |
| S2 | **Critical** | `/rudra/send` passes the entire user row (including `password_hash`, `api_token_hash`) into the LLM system prompt sent to third-party APIs | `src/webapp/views.py:853-856`, `src/ai.py:307-315` |
| S3 | High | No CSRF tokens anywhere; only Origin==Host check which is skipped when Origin absent | `views.py:117-128` and all forms |
| S4 | High | Session tokens stored plaintext in DB → any DB read enables session hijack | `src/db.py:743-773` |
| S5 | High | Unauthenticated agent-execution endpoint: `POST /api/agents/{id}/run` triggers agents anonymously; also unauthenticated `/crawl/jobs`, `/stats`, `/report`, all `/api/*` reads | `src/api.py:266-271,146,151,161,180-264` |
| S6 | Medium | Session/state cookies missing `Secure` flag | `views.py:78-86,813` |
| S7 | Medium | OAuth account linking on unverified email → pre-hijack/takeover vector | `src/webapp/oauth.py:171-175` |
| S8 | Medium | Non-constant-time token compares on `/run`, `/crawl` | `src/webhook.py:20-25`, `src/api.py:173` |
| S9 | Medium | Crawled URLs rendered into `href` without scheme allow-list (`javascript:`/`data:` possible) | `templates/detail.html:57`, `_items.html:43`, `resources.html:21` |
| S10 | Medium | Host-header poisoning of canonical/OG/sitemap URLs | `templates/base.html:8-14`, `views.py:461,471` |
| S11 | Medium | sitemap.xml built by raw concatenation without XML escaping | `views.py:482-503` |
| S12 | Medium | Internal error strings returned to clients | `webhook.py:86-87` |
| S13 | Low | In-memory rate limiting only (resets on restart, per-process) | `views.py:89-104` |
| S14 | Low | Autofill bearer lookup runs scrypt against every row (CPU DoS at scale) | `views.py:1094-1099` |
| S15 | Low | Anonymous unthrottled report endpoint (queue poisoning) | `views.py:355-369`, `api.py:161` |
| S16 | Info | No hardcoded secrets found; `.env` properly gitignored; parameterized SQL everywhere (no SQL injection found) | — |

### 3.2 Broken functionality (P0)

| # | Finding | Location |
|---|---|---|
| B1 | Orchestrated agent pipeline broken after stage 3: ExtractionAgent emits `{"opportunities": [...]}` wrapper but downstream stages receive it as a single opportunity → every downstream stage processes `None` fields | `src/agents/orchestrator.py:175-185` vs `src/agents/extraction.py:68-72` |
| B2 | Retry/dead-letter machinery dead code: `fail_crawl_job()` and `next_crawl_jobs()` are never called → RETRYING unreachable, FAILED jobs never retried automatically | `src/db.py:1413-1424,1442-1457` |
| B3 | One stale QUEUED job row permanently blocks all future enqueues | `src/queue.py:18-21` |
| B4 | `fastapi`/`uvicorn`/`pydantic` absent from requirements.txt; compose pip-installs them unpinned at container start | `requirements.txt`, `docker-compose.yml:79` |
| B5 | Change detection not implemented: `record_opportunity_change()` has zero callers; ChangeDetectionAgent reads an always-empty table and takes no action | `db.py:1688`, `src/agents/change_detection.py` |
| B6 | Evidence tables never populated: `AgentEvidence` objects are built then discarded; `opportunity_evidence`/`agent_metrics` tables have zero writers | `src/agents/base.py`, `db.py:341` |
| B7 | `validate_opportunity()` exists but is never called in production write path | `schema.py:161-179`, `db.py:419` |
| B8 | Natural-language-search ignores its own parsed `field`/`funding`/`year` filters | `src/agents/natural_language_search.py:117-139` |
| B9 | Time-bomb tests hardcode dates (4 currently failing) | `tests/test_deadlines.py:25,31,38,56` |
| B10 | Manual agent-run endpoints invoke agents with `{}` input producing junk task records | `api.py:285-289`, `views.py:1028-1031` |
| B11 | `agent_tasks.input_data` stores output data; `event_id` generated but never persisted | `base.py:214,49` |
| B12 | `POST /report` returns wrong id (opportunity id instead of report id) | `api.py:165-166` |
| B13 | Exception mid-pipeline skips run logging; no concurrency guard on overlapping runs | `worker.py:53-72` |
| B14 | FTS index fully rebuilt on every `init_db()` (every pipeline run) | `db.py:160`, `worker.py:45` |

### 3.3 Architecture weaknesses (P1)

1. **Two parallel pipelines.** The real worker uses legacy scouts directly; the 16-agent orchestrator is a vestigial monitoring layer only reachable via manual triggers that pass empty input. The "agent system" records telemetry but drives nothing.
2. **No agent input/output schema validation**, declared retry constants unused, no timeouts.
3. **SQLite shared by 3 containers without WAL or busy_timeout** → `database is locked` under concurrent writes. PostgreSQL migration deferred.
4. **Dual schema definitions drift risk** (`database/schema.sql` vs inline DDL in `db._migrate()`); `database/agent_schema.sql` is dead; no versioned migrations.
5. **Classification quality**: substring matching misclassifies (`"ai"` matches "email", `"cs"` matches "physics"); two divergent classifiers coexist (ClassificationAgent vs scout `classify_category`); hardcoded 0.8 confidence regardless of evidence.
6. **LLM layer**: no unified gateway; assess() ignores OpenAI/Gemini even when configured (Ollama-only); OpenAI/Ollama have no retry; no token/cost tracking; nested verdict sections demanded by prompt but never validated/used; extra HTTP roundtrip to Ollama before every assess call.
7. **Prompt-injection defenses**: none. Advisory-only storage caps blast radius for assess(), but Rudra chat has no grounding/citation enforcement.
8. **Link checking**: attempts=1, 403/429 counted as dead (bot-blocked live links falsely killed), soft-404s count as live.
9. **Dedup**: raw-string deadline comparison treats ISO variants as conflicting; no org-name normalization.
10. **GPA scale bug**: 4.0-scale thresholds compared against 10-point CGPA → false not_eligible (documented, unresolved).

### 3.4 Testing gaps

- No CI/CD at all.
- No tests for CSRF guard behavior, admin escalation, cookie flags, URL-scheme filtering, rate limiting.
- Time-dependent tests use hardcoded dates (currently 4 failing).
- No integration test exercising the orchestrator end-to-end (would have caught B1).
- No lint/typecheck configuration (ruff/mypy absent).
- No AI evaluation harness (extraction accuracy, hallucination rate) — nothing fabricated, nothing measured either.

### 3.5 Deployment gaps

- Web image unbuildable standalone (Dockerfile copies only requirements.txt; relies on host mounts; ships pytest into prod image).
- Flask dev server in production.
- n8n deployed with auth disabled and empty-password default; env access enabled.
- `.env.example` omits RUN_TOKEN, SESSION_SECRET, OAuth credentials; default model name `gemini-3.6-flash` does not exist.
- SESSION_SECRET defaults to `change-me`.

---

## 4. Data-quality assessment

Strengths: deterministic extraction, advisory-only LLM, dedup before publish, trust gating of "verified", closed items hidden, review queue for unclear items.

Residual risks:

1. Regex extractor can bind wrong values from boilerplate text (deadline/stipend/GPA enter DB as facts with no provenance/evidence trail).
2. HTML-title scraping can store site chrome as opportunity title; country inferred from any keyword occurrence in first 10K chars.
3. QC agent only runs in the broken orchestrated path; real ingestion publishes eligible items immediately without QC checks.
4. No change history: re-crawls blind-overwrite columns (`upsert_opportunity`) so silent mutations are invisible.
5. Every new user gets a clone of the owner's personal profile (`config/profile.json`) as their seed profile.

---

## 5. Recommended target state (evolutionary, not rewrite)

Preserve the deterministic spine. Converge the two pipelines into one agent-based pipeline. The priority order used for implementation:

```text
P0  Security criticals + broken core (S1-S5, B1-B9)
P1  Reliability & architecture (retries/DLQ wired, migrations versioning,
    constant-time auth, secure cookies, rate limiting, URL scheme allow-list,
    evidence persistence, change detection wiring)
P2  Data pipeline quality (QC in real path, classification fix,
    verification hardening, GPA scale handling)
P3  AI intelligence (LLM gateway with retries/token accounting,
    provider routing for assess(), prompt-injection hardening, grounding)
P4  Frontend/admin polish (admin audit logs, merge duplicates UI)
P5  Observability (structured logging, metrics, cost tracking)
P6  Security hardening round 2 (OAuth verified-email, autofill perf,
    host-header pinning)
P7+ CI/CD, packaging, docs alignment
```

Key architectural decisions:

1. **Keep SQLite as default engine** (zero-deploy philosophy, works everywhere) but make the storage layer correct: WAL mode, busy_timeout, hashed sessions, atomic migrations with `schema_version`. PostgreSQL remains a documented future migration, not a pretend one.
2. **One pipeline**: wire the working scouts *through* the orchestrator contract rather than maintaining two systems; fix the inter-stage contract (B1) so the orchestrated path actually functions.
3. **Evidence-first**: persist AgentEvidence to `opportunity_evidence`; record field-level changes via `record_opportunity_change` during upsert diffing.
4. **Security invariants**: RBAC via explicit role column; CSRF tokens on all state-changing forms; hashed session tokens; constant-time token compares; URL scheme allow-list; sanitized profile projection for LLM prompts.

---

## 6. What was NOT done and why

- **PostgreSQL/pgvector migration**: deliberately deferred. The current product is single-node; migrating now adds ops burden without user value. Storage layer is being made portable-correct instead. Documented in roadmap.
- **Redis/RQ job infrastructure**: the DB-backed queue is adequate at current scale once retry wiring is fixed (B2/B3). Revisit when multi-worker crawling is needed.
- **Headless-browser crawling**: current sources are all JSON-API/RSS/PDF based; adding Playwright would be speculative weight.
