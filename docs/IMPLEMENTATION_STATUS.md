# AAWARA Implementation Status

Live tracker for the production-readiness program defined in
`docs/PRODUCTION_ROADMAP.md`. Statuses: `COMPLETE`, `IN_PROGRESS`, `BLOCKED`,
`NEEDS_REVIEW`.

**Last verified:** 2026-08-24 — full test suite: **527 passed / 0 failed**
(`python3 -m pytest -q`).

---

## COMPLETE

### Hackathon discovery (2026-08-24)
| Item | Evidence |
|---|---|
| Common hackathon source-adapter layer (one interface, per-platform adapters — no independent scrapers) | `src/discovery/hackathon_sources.py` |
| Live-verified adapters: **Devpost** (public JSON API; dates/prizes/themes/orgs), **MLH** (Inertia page-props JSON, upcomingEvents only), **Internshala** (server-rendered titled links) | live run: 21 opportunities ingested (9 Devpost + 12 Internshala); `tests/test_hackathon_scout.py` with recorded fixtures |
| 12 further sources (Unstop, SIH, HackerEarth, DoraHacks, lablab, TAIKAI, IBM, SAS, Bhashini, HackIndia, Reskilll, WeMakeDevs) configured **disabled with honest probe reasons** (JS-rendered / auth-gated) — no fake scraping | `config/sources.json` `_note` fields |
| Never-guarantees hold: missing deadlines stay null (e.g. Internshala cards carry no machine-readable dates); prizes → funding field; themes/team size → requirements; online mode → remote flag | `hackathon_scout.entry_to_opportunity` |
| Wired into the scheduled pipeline (`worker.run_pipeline`) and Rudra's `search_opportunities` tool surfaces them automatically | worker summary now includes `hackathon_scout` count |

### Rudra floating assistant + Groq provider (2026-08-24)
| Item | Evidence |
|---|---|
| Floating widget (bottom-right launcher → 400×600 panel; mobile bottom-sheet; minimized/loading/streaming/error states; ARIA + keyboard nav + reduced-motion) | `templates/_rudra_widget.html`, `static/rudra-widget.{js,css}`; rendered only for logged-in users when `RUDRA_WIDGET_ENABLED` |
| Rudra API: SSE chat streaming, non-stream fallback, new-chat/clear/feedback/suggestions endpoints, per-user rate limiting, CSRF enforced | `views.py` `/rudra/api/*`; `tests/test_rudra_widget.py` |
| Controlled tool layer (`search_opportunities`, `get_opportunity`, `check_eligibility`, `get_match_score`, `get_skill_gaps`, `analyze_resume`, `get_deadlines`, `get_saved_opportunities`, `get_application_status`) — user-scoped, arg-whitelisted, deterministic intent router | `src/rudra/tools.py`, `orchestrator.py`; no arbitrary DB access path |
| Context awareness: page hints resolved server-side from DB (client cannot spoof titles/deadlines); minimum-necessary whitelisted projections | `src/rudra/context.py`; spoof test |
| Prompt-injection defense: crawled text wrapped in `<untrusted_opportunity_data>` with explicit data-only instructions; FACT/RECOMMENDATION labeling protocol | `orchestrator.format_facts`, `SYSTEM_PROMPT_RUDRA_V2` |
| Conversations: server-side conversation ids, history hydration, feedback (👍/👎) stored owner-scoped | `db.py` chat functions + migration |
| **Groq as primary LLM provider** (OpenAI-compatible; streaming via SSE). Chain: **Groq → OpenAI → Gemini → Ollama**. Cloudflare UA requirement handled. Live-verified: chat + 16-fragment stream + full widget turn with tools | `src/ai.py` (`_groq_chat`, `groq_stream`, `_openai_style_chat`), `tests/test_ai_groq.py` |
| Test hermeticity: autouse fixture strips local `.env` provider keys from the test process so real APIs are never called from CI/tests | `tests/conftest.py::_isolate_ai_providers` |

### Phase 0 — P0 security criticals & broken core
| Item | Evidence |
|---|---|
| RBAC role column; admin gate no longer username-based; reserved names blocked at registration | `src/db.py` (`set_user_role`, `bootstrap_admin`), `src/webapp/views.py` (`_admin_required`); tests in `tests/test_security_p0.py` |
| LLM prompts receive whitelisted profile only (`ai.safe_profile`) — no password/API-token hashes leave the perimeter | `src/ai.py`; tests assert hashes absent from captured prompts |
| CSRF tokens: stateless HMAC(session) tokens + anonymous double-submit cookie; enforced in `before_request`; all POST templates updated | `src/webapp/views.py` (`csrf_token*`, guard), templates; 5 dedicated tests |
| Session tokens hashed at rest (SHA-256) with transparent legacy upgrade (`token_algo` marker); leaked DB values cannot authenticate | `src/db.py`; 4 tests |
| FastAPI internal endpoints token-gated (`/crawl/jobs`, `/stats`, `/api/*` reads + agent execution); constant-time token compares everywhere | `src/api.py`, `src/webhook.py`; tests |
| Secure cookie policy (`COOKIE_SECURE=auto\|force\|never`) on session/OAuth-state/anon-CSRF cookies | `views._cookie_secure` |
| Orchestrator data-contract fixed: per-opportunity stages run once per extracted opportunity with dependency-aware skipping | `src/agents/orchestrator.py`; 5 contract regression tests |
| Crawl-job retries wired end-to-end: scouts share worker `run_id`, `settle()` reconciles real per-source results, stale-queue recovery + RETRYING reactivation | `src/queue.py`, `src/worker.py`, scouts, `db.expire_stale_crawl_jobs`; 9 tests |
| requirements.txt complete+pinned; compose hardened (no runtime pip install, n8n auth mandatory, env access blocked, invalid model name removed) | repo root |
| Time-bomb tests converted to dynamic dates | `tests/test_deadlines.py`, fixtures |

### Phase 1 — P1 reliability & architecture
| Item | Evidence |
|---|---|
| SQLite hardening: WAL mode + busy_timeout=5000 on every connection; FTS rebuild only when FTS wiring changes (was every pipeline run) | `src/db.py:get_connection/_migrate` |
| URL scheme allow-list (`http`/`https`) enforced at write path (`normalize_opportunity`) and render time (`safe_url` filter); `javascript:`/`data:` from crawled content can never reach `href` | `src/schema.py:sanitize_url`; templates; tests |
| Sitemap XML-escaped + lastmod format-checked; canonical/OG/sitemap URLs pinned to `PUBLIC_BASE_URL` env (host-header poisoning mitigated) | `views.sitemap`, `_public_base_url`, `base.html` |
| Internal error details never returned to clients (webhook `/run`, webapp `/run`) | both handlers; test asserts `"kaboom"` not leaked |
| Agent telemetry fixed: `agent_tasks.input_data` stores input; `event_id` persisted (column added via migration) | `src/agents/base.py`, `src/db.py:_migrate` |
| Change detection implemented: tracked-field diffs recorded with old/new values on every re-crawl upsert; `opportunity_changes` table finally has a writer | `db.upsert_opportunity`/`_diff_opportunity`; tests |
| Validation in production write path (`validate_opportunity` before persist) | `db.upsert_opportunity` |
| Pipeline run logging guaranteed via try/except (failed runs are logged as failed); full-uuid run ids | `src/worker.py` |
| Rate limiting: global per-IP throttle middleware on FastAPI API; anonymous report endpoints throttled (web + API) | `src/api.py`, `views.report_opportunity` |
| OAuth email-linking requires provider-verified email; GitHub fetches primary verified email from `/user/emails` — unverified-email account takeover closed | `src/webapp/oauth.py`; takeover test |

### Phase 2 — P2 data pipeline quality (partial)
| Item | Evidence |
|---|---|
| Classification word-boundary matching ("ai" no longer matches "email", "cs" no longer matches "physics"); evidence-based confidence; new fields (cybersecurity/cloud) | `src/agents/classification.py`; tests |
| Verification treats HTTP 403/429 as "error" (bot wall) instead of "dead" — bot-blocked live links are no longer falsely killed | `verification.check_link`; tests |
| GPA scale normalization: explicit 4.0-scale thresholds ("3.5 GPA", "3.5/4") converted ×2.5 before comparison against 10-point CGPA | `scoring._parse_min_gpa`; tests |

---

## IN_PROGRESS

*(none — next items queued below)*

## NEEDS_REVIEW

- **Orchestrator integration depth**: the orchestrated pipeline now works and is
  contract-tested, but is still triggered manually/admin-only. Wiring it as THE
  ingestion path (replacing direct scout calls) is deliberate later work — the
  scouts remain authoritative until extraction quality justifies the switch.

## BLOCKED

- None currently.

## NOT STARTED (per roadmap)

- Phase 3: unified LLM gateway (retries/token accounting), Rudra RAG grounding,
  prompt-injection scrubbing.
- Phase 4: admin audit log of manual actions; duplicate-merge UI; profile wizard.
- Phase 5: CI pipeline, structured logging/metrics, WSGI server, Dockerfile
  verification build.

## Known limitations (honest)

1. SQLite remains the store (WAL-hardened). PostgreSQL/pgvector migration deferred
   by design (single-node product today).
2. Rate limiting is in-process; multi-worker deployments need Redis-backed limits.
3. The crawl queue is DB-backed bookkeeping driven by the scouts, not a separate
   worker pool — adequate at current scale, revisit when crawling parallelizes.
