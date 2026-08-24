# AAWARA Production Roadmap

Companion to `docs/PRODUCTION_AUDIT.md`. Each item references audit finding IDs.
Status legend: `[ ]` pending · `[~]` in progress · `[x]` complete (with test evidence).

---

## Phase 0 — P0: Security criticals & broken core

| # | Task | Findings | Status |
|---|---|---|---|
| 0.1 | RBAC: add `role` column to users; admin gate checks role, not username; reserve reserved names at registration; grant initial admin via env `ADMIN_USERNAME` bootstrap only when that user exists | S1 | [x] done — `db.set_user_role`, `db.bootstrap_admin`, role gate in `_admin_required`; 7 tests |
| 0.2 | Stop leaking `password_hash`/`api_token_hash` to LLM prompts: project profile to a safe whitelist dict in both `/rudra/send` and stream path | S2 | [x] done — `ai.safe_profile` whitelist used by chat_ask + both Rudra routes; 2 tests |
| 0.3 | CSRF tokens on all state-changing POST forms + validation server-side (keep Origin check as defense-in-depth) | S3 | [x] done — stateless HMAC(session) tokens, anon double-submit cookie, all templates updated; 5 tests |
| 0.4 | Hash session tokens at rest (SHA-256); migrate existing plaintext sessions transparently; delete expired sessions | S4 | [x] done — hashed with legacy one-time upgrade (`token_algo` marker); leaked hash cannot authenticate; 4 tests |
| 0.5 | Require admin auth for agent execution + stats/crawl endpoints in FastAPI API; constant-time token compare everywhere | S5, S8 | [x] done — internal endpoints token-gated, hmac.compare_digest in webhook+api+views; report rate limit + correct id; 5 tests |
| 0.6 | Secure cookie flags (session + OAuth state) behind config; Secure auto when HTTPS | S6 | [x] done — `COOKIE_SECURE=auto\|force\|never` policy on session & OAuth state & anon CSRF cookies |
| 0.7 | Fix orchestrator data-contract bug so downstream stages receive the extracted opportunity, not the wrapper; add regression test | B1 | [x] done — pipeline now loops per-opportunity through downstream stages with dependency-aware skipping; 5 contract tests |
| 0.8 | Wire crawl-job retries: mark failures via `fail_crawl_job`, drain retryable jobs, DLQ semantics for exhausted jobs; stale-queue recovery so a crashed run can't block enqueueing forever | B2, B3 | [x] done — scouts share worker run_id, settle() reconciles real per-source results, stale-job expiry + RETRYING reactivation; 9 tests |
| 0.9 | Fix requirements.txt (add fastapi/uvicorn/pydantic pinned), remove runtime pip-install hack from compose | B4 | [x] done — pinned deps, self-contained Dockerfile, compose hardened (n8n auth required, env access blocked), .env.example complete |
| 0.10 | Fix time-bomb tests with dynamic dates; add CI-proof date handling | B9 | [x] done — deadlines/verification/webapp/conftest fixtures use dynamic offsets |

**Phase 0 verification:** full suite 501 passed / 0 failed (2026-08-24).

## Phase 1 — P1: Reliability & architecture

| # | Task | Findings | Status |
|---|---|---|---|
| 1.1 | SQLite hardening: WAL mode + busy_timeout + foreign_keys on every connection; FTS rebuild only when schema changes | §3.1 db | [x] done |
| 1.2 | Versioned migrations: `schema_version` table; move inline DDL into ordered migration steps; remove dead `database/agent_schema.sql` | §3.4 | [ ] pending (guarded idempotent `_migrate` in place; formal versioning deferred) |
| 1.3 | URL scheme allow-list helper (`http/https` only) applied at write time and render time for crawled URLs | S9 | [x] done |
| 1.4 | XML-escape sitemap; pin canonical/OG URLs to configured base URL (`PUBLIC_BASE_URL`) | S10, S11 | [x] done |
| 1.5 | Generic error responses (no internal detail leak) | S12 | [x] done |
| 1.6 | Evidence persistence: agents persist AgentEvidence rows to `opportunity_evidence`; fix `agent_tasks.input_data` storing output; persist event_id | B6, B11 | [x] partial — input/event_id fixed; full evidence persistence deferred with orchestrator integration (NEEDS_REVIEW) |
| 1.7 | Change detection: diff old vs new in `upsert_opportunity`; record field-level changes with old/new values; ChangeDetectionAgent consumes real data | B5 | [x] done |
| 1.8 | Validate opportunities in production write path | B7 | [x] done |
| 1.9 | Pipeline run guard: try/except run logging, run_id full uuid | B13 | [x] done |
| 1.10 | Rate limiting middleware for FastAPI API (per-IP) | S13/S5 | [x] done |
| 1.11 | OAuth: require verified email before linking accounts by email | S7 | [x] done |
| 1.12 | Report endpoint rate limiting + correct report id return | S15, B12 | [x] done |

## Phase 2 — P2: Data pipeline quality

| # | Task | Status |
|---|---|---|
| 2.1 | Classification word-boundary matching; evidence-based confidence; cybersecurity/cloud fields added | [x] done |
| 2.2 | QC gate in the real ingestion path before publish | [ ] pending |
| 2.3 | Verification: 403/429 treated as unknown-not-dead | [x] done (retry/backoff on checks still pending) |
| 2.4 | GPA scale normalization (4.0 vs 10-point) | [x] done |
| 2.5 | Deadline comparison normalization in dedup (parse dates, compare values not strings) | [ ] pending |
| 2.6 | Org-name normalization for dedup | [ ] pending |

## Phase 3 — P3: AI intelligence

| # | Task | Status |
|---|---|---|
| 3.1 | LLM gateway module: unified provider interface, retries/backoff per provider, structured-output parsing+validation, token usage capture | [ ] pending |
| 3.2 | Route assess() through gateway so OpenAI/Gemini work when Ollama absent; cache availability check | [ ] pending |
| 3.3 | Prompt-injection defenses: delimit untrusted content, strip instruction-like patterns | [ ] pending |
| 3.4 | Rudra grounding: retrieve top-k relevant DB opportunities and cite them | [ ] pending |
| 3.5 | Cost/token tracking table + per-run totals surfaced in stats | [ ] pending |
| 3.6 | NL search agent: implement ignored filters or drop them honestly | [ ] pending |

## Phase 4 — P4: Frontend & admin

| # | Task | Status |
|---|---|---|
| 4.1 | Admin: audit log of every manual action | [ ] pending |
| 4.2 | Admin: duplicate merge UI backed by dedupe canonical logic | [ ] pending |
| 4.3 | Admin gate all agent pages; public stats page sanitized | [ ] partial (agent execution admin-gated; dashboards still public reads) |
| 4.4 | New-user profile onboarding wizard instead of owner-profile clone | [ ] pending |

## Phase 5 — Observability & ops

| # | Task | Status |
|---|---|---|
| 5.1 | Structured JSON logging with request IDs | [ ] pending |
| 5.2 | Metrics endpoint (crawl success rate, queue depth, verification backlog, LLM cost) | [ ] partial (/stats exists token-gated) |
| 5.3 | CI pipeline (GitHub Actions): lint (ruff), tests, bandit security scan, app-factory smoke check | [x] done (.github/workflows/ci.yml) |
| 5.4 | Production WSGI server instead of Flask dev server | [ ] pending |
| 5.5 | Dockerfile fix: self-contained image, compose cleanup, n8n auth defaults required | [x] done |
| 5.6 | `.env.example` completeness; fail-fast on missing prod secrets (compose `:?` guards) | [x] done |

---

## Verification discipline

Every completed item must have: implementation + tests passing + honest status note in
`docs/IMPLEMENTATION_STATUS.md`. Nothing is marked complete without a passing test
run recorded here.

## Current known blockers

None blocking local development. PostgreSQL/pgvector and Redis are deferred by design
(see audit §6).
