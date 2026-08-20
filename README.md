# Opportunity Radar

Zero-budget automated discovery of fellowships, scholarships and internships
(Indian student, B.Tech CSE). Built on self-hosted n8n + SQLite + local Ollama.

## Phase 18 — Discovery overhaul (more + better internships)

- **14 verified official ATS sources added** (probed live, public APIs only):
  GitLab, Twilio, Affirm, Mercury, OpenAI, Pinterest, Roblox, Brex, HackerRank,
  PlanetScale, Duolingo, Temporal, Firecrawl, Sentry (see `config/sources.json`)
- **Pagination**: offset/cursor pagination for JSON APIs (Amazon
  `search.json` now yields all ~195 intern jobs instead of 100) with a generic
  loop that stops on short pages, `total` field (dotted paths like
  `content.hits.total` supported) or per-source page limits
- **Per-source config** in `sources.json`: `max_pages`, `result_limit`,
  `rate_limit_ms`, `location_filter` (`india_remote` (default) | `any`),
  `role_patterns` (word-boundary match, e.g. `intern` matches "internship" but
  not "International"; default: intern/graduate/university/scholar/apprentice/
  trainee/fresher/summer/research assistant/new grad)
- **Location policy**: sources with `location_filter: any` (OpenAI, Pinterest,
  Roblox, Brex) keep foreign-onsite roles — they are stored as `unclear` and
  land in the review queue instead of being dropped
- **Resilience**: fetcher now has env-configurable timeout (`REQUEST_TIMEOUT_MS`
  = 20000), retries with exponential backoff (`MAX_RETRIES` = 3), 429 handling
  with cooldown, fail-fast on 404/403, per-domain delay (`PER_DOMAIN_DELAY_MS`
  = 1500), and per-source cooldown after repeated failures; one dead source no
  longer leaves a silent hole (`consecutive_failures`/`cooldown_until` tracked)
- **Observability**: every run writes per-stage counters to `discovery_runs`
  (raw → role gate → location gate → pattern gate → extracted → stored →
  published), rejections to `filtering_decisions`, raw dumps to
  `data/debug/` when `DEBUG_DISCOVERY`/`SAVE_REJECTED`/`SAVE_RAW_RESPONSES`
  are on; `python -m src.worker` now prints a discovery summary with totals,
  failed sources and top rejection reasons
- **Web filtering**: lists default to *published* (eligible + likely_eligible)
  only; `unclear` items are hidden behind the review queue (`/review` or the
  "Review queue" select) and `not_eligible` is never shown as a recommendation
- Result of a live run: ~15,800 raw jobs → 929 role-gate passes → 33 new
  stored → 28 published (was ~12 before this phase); cumulative numbers are
  visible on `/stats` and in `discovery_runs`

## Phase 17 — Web app (replaces the Telegram bot)

- The primary front-end is now a self-hosted website (Flask + Jinja templates,
  no external CDNs) served on `http://localhost:8080` by the `web` service
  (`python -m src.webapp`)
- Browse every collected opportunity: `/opportunities`, `/internships`,
  `/fellowships` with search, sort (score/deadline/newest) and pagination;
  `/top` (best matches), `/urgent` (deadlines within 14 days), `/saved`
- Detail pages (`/o/<id>`) show the full record: eligibility status + reasons,
  dates, stipend/funding, eligible criteria, requirements, AI cross-check and
  apply links; nothing stored is ever hidden
- **Accounts**: register/login/logout (scrypt-hashed passwords, DB-backed
  sessions), per-user profiles and per-user bookmarks (`bookmarks` table)
- **OAuth sign-in**: "Continue with Google" / "Continue with GitHub" buttons
  on login and register (authorization-code flow with CSRF state, stdlib
  `urllib` only — no extra dependencies). First-time users get a seeded
  profile + auto-login; an existing account with the same email is linked
  instead of duplicated. Requires `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`,
  `GITHUB_CLIENT_ID`/`GITHUB_CLIENT_SECRET` and `OAUTH_REDIRECT_BASE`
  (default `http://localhost:8080`; register callback URLs
  `http://localhost:8080/auth/google/callback` and
  `http://localhost:8080/auth/github/callback`)
- Personalized scoring: match score + eligibility are computed per logged-in
  user (in-memory, read-only) instead of overwriting the shared pipeline scores
- The scheduled pipeline is unchanged: n8n still POSTs `/run` with `X-Run-Token`
  on the 08:00 / 18:00 IST cron; Telegram sending is disabled via
  `SEND_TELEGRAM=false` so the pipeline stores everything without messaging
- `GET /health`, `GET /stats.json` (token-protected) and `/stats` page expose
  pipeline status and run history

## Phase 16 — Hardening & monitoring

- `src/maintenance.py` — idempotent upkeep on every pipeline run: passed
  deadlines → `status='expired'`; prunes execution_logs/system_errors older
  than 90 days and notifications older than 180 days
- `src/worker.py` now logs one run-level `execution_logs` row with the full
  JSON summary per pipeline run
- Webhook `GET /stats` (token-protected) exposes counts + last pipeline
  summary; Telegram `/stats` shows the same
- Live run: one expired opportunity correctly marked; /stats returns
  real counts (19 opportunities, 4 verified, 6 AI assessments, 20 sources)

## Phase 16b — Startup-friendly eligibility & India focus

- New `evaluate_eligibility` policy in `src/scoring.py`: hard exclusions ONLY
  when explicitly stated (expired deadline, countries excluding India,
  incompatible degree/branch, incompatible year, explicit work-authorization
  requirement). Missing formal criteria are NOT disqualifications.
  - Credible Indian-startup role, no restriction → `eligible`
  - Credible foreign remote startup role, criteria not specified → `likely_eligible`
  - Explicitly open to international applicants / visa sponsorship → `eligible`
  - Unverifiable source or unresolved location/work-auth → `unclear`
- Score caps: `not_eligible`=0, `unclear`≤59, `likely_eligible`≤79
- AI layer returns the full structured policy JSON (india/degree/branch/year/
  location/overall eligibility + verification + recommendation), advisory-only
- Telegram labels: "Apply now — Eligible", "Likely eligible — remote startup;
  criteria not specified", "Unclear — verify before applying"; notifications
  send eligible/likely/unclear, never rejected
- Internship sources focused on India + remote (Postman, Stripe, Airbnb,
  Amazon India via a new `ats_json` adapter); junk sources (UGC letters,
  news/MoU/result notices) excluded or disabled
- Profile onboarding: guided /start flow (year → degree → branch → skills →
  interests), profile now carries citizenship, degree_level, eligible_years
- Every card/list shows a date: deadline when known, otherwise the listed date

## Phase 15 — Interactive Telegram cards

- Every opportunity can now be sent as an **interactive card** with inline
  buttons: 🔖 Save (toggle, updates the button live), ℹ️ Details, 🔗 Apply
- `src/notifications/cards.py` — pure, tested card logic (64-byte-safe
  callback data, strict decode, apply-URL priority)
- `/top`, `/urgent` and `/saved` render cards; callback handlers in
  `telegram_bot.py` toggle the `saved` flag, re-send details or open the
  application link
- `db.toggle_saved()` added; the stdlib sender now supports `reply_markup`
- Verified live: an interactive card with working buttons was delivered to
  the registered Telegram chat (message 70)

## Phase 14 — AI (Ollama, advisory)

- **`src/ai.py`**: talks to local Ollama (`host.docker.internal:11434`,
  DeepSeek-R1:8b, stdlib-only HTTP client)
- Strict-JSON eligibility cross-check per opportunity (verdict/reason/
  deadline_guess/confidence); results live in `ai_assessments` —
  **advisory only**, rule-based `eligibility_status`/`deadline` are never
  overwritten
- Fallback: if Ollama is down or the answer is unparsable the pipeline just
  skips the AI step (current SQLite logic stays authoritative); `think=false`
  + capped tokens keep answers fast and JSON-shaped
- Wired into `src/worker.py` (`ai_assessments` in the summary) and runnable
  standalone: `python -m src.ai --limit N`
- Live: reachable, 6 assessments recorded, verdicts sensible (e.g. 1st-year
  vs "Jr. Engineer" → not_eligible)

## Phase 13 — Scheduling (n8n)

- `src/worker.py` — one entry point: both scouts → notifier; prints a JSON
  summary (also `python -m src.worker`)
- `src/webhook.py` — local stdlib HTTP server (port 8080): `GET /health`,
  `POST /run` (requires `X-Run-Token: $RUN_TOKEN`); runs the pipeline and
  returns the summary JSON
- `src/main.py` — the bot container now runs the Telegram poller and the
  webhook side by side (threads)
- n8n workflow `workflows/opportunity-daily.json` (imported, active):
  Schedule trigger (daily 08:00 & 18:00 IST) → HTTP POST to
  `http://telegram-bot:8080/run` with the shared token
- Verified end-to-end: workflow payload executed from inside the n8n
  container → full pipeline run → `execution_logs` trail (opportunities
  stayed 19, 0 duplicates); workflow state confirmed `active=True` via the
  n8n public API (`GET /api/v1/workflows`, key in `.env` → `N8N_API_KEY`)
- Notes from real setup: n8n's `n8n import:workflow` in 2.35.3 requires a
  root `id` in the JSON (else `NOT NULL workflow_entity.id`); `N8N_API_KEY`
  is ignored when user management is disabled, so basic auth is enabled
  (`N8N_BASIC_AUTH_*`) and n8n is bound to 127.0.0.1

## Phase 12 — Notifications

- **`src/notifications/notifier.py`**: two quiet-by-design channels
  - New opportunities: match_score >= 30 AND verified/official AND not
    `not_eligible`; each opportunity alerts exactly once (idempotent)
  - Deadline reminders per bucket — 30d / 14d / 7d / 3d / 24h — each bucket
    fires exactly once via the `deadlines` table flags; expired deadlines are
    auto-marked; duplicates and `not_eligible` items never nag
- Every attempt is recorded in `notifications` (delivered 1/0); failures
  retry on the next run
- `--dry-run` is a pure preview (sends nothing, records nothing)
- Run: `docker compose run --rm telegram-bot python -m src.notifications.notifier`
- Uses the shared stdlib Telegram sender + the chat_id the bot captures via
  `/start`; verified end-to-end against the live bot

## Phase 11 — Verification & trust

- **`src/verification.py`**: an opportunity is only `verified` when its
  application link is live AND the source is official (trust >= 90) or the
  item is corroborated by >= 2 independent sources
- Link checks: one attempt, 10s timeout, 64 KB cap; HTTP 4xx/5xx → `dead`
  (downgraded to unverified), network errors → keep current status
  (transient failures never downgrade), live → verified/unverified with the
  reason recorded
- History in the `verifications` table; scouts verify every newly discovered
  opportunity; backfill CLI:
  `docker compose run --rm telegram-bot python -m src.verification`
- `fetcher.FetchError` now carries the HTTP status code; HTTP errors fail
  fast instead of retrying

## Phase 10 — Scoring & eligibility

- **`src/scoring.py`**: deterministic, explainable match scoring vs the user
  profile — skills overlap (25), interests/category (20), degree (15), year
  (15), branch (10), country (10), funding preference (10), allowed types (5)
- Confidence-weighted: 100% is reachable only when every component is
  comparable AND matches; sparse opportunities score proportionally lower;
  missing info is neutral, never penalized
- `evaluate_eligibility()` → `eligible` / `not_eligible` / `unknown` with
  reasons (degree/year/branch/country) — generic "undergraduate" matches
  B.Tech/B.E./B.Sc., "postgraduate" matches M.Tech/M.Sc/PhD
- Stored per user in `scores` + `eligibility_results`, mirrored onto
  `opportunities.match_score` / `eligibility_status`; wired into both scouts
  and a backfill CLI: `docker compose run --rm telegram-bot python -m src.scoring`
- `/top` now ranks by real profile match; live verdicts verified manually
  (Modal "ML Research Intern" requires PhD → not_eligible; UGC NSPG is
  postgraduate-only → not_eligible)

## Phase 9 — Deduplication

- **Exact duplicates**: blocked by the unique `dedup_key` (title|org|url|deadline)
- **Near duplicates**: `src/dedupe.py` catches the same program re-listed with
  slightly different titles (extra parentheses, commas, cycle tags) — pure
  stdlib similarity (SequenceMatcher + token Jaccard), threshold 0.85
- Only same organization + same type are compared; conflicting deadlines
  (different cycles) are never merged
- The newer record is marked `duplicate_of` the older canonical one, logged in
  the `duplicates` table, and hidden from `/opportunities` and the bot lists;
  a missing deadline on the canonical record is copied over from the duplicate
- Wired into both scouts; execution logs report `duplicates=N`

## Phase 8 — Field extraction from text + PDFs

- **`src/extraction/extractor.py`**: deterministic regex extraction (no AI,
  nothing invented) — deadline (keyword proximity, never hallucinated),
  duration, stipend/funding (INR/USD/EUR/GBP), GPA, eligible degrees/years/
  branches/countries, preferred skills
- **`src/extraction/pdf.py`**: local PDF text extraction via `pypdf`
- **`src/discovery/entries.py`**: shared entry fetching for both scouts —
  `rss` / `html_news` / `html_links` / `ats_greenhouse` / `ats_ashby` /
  `pdf_links` (downloads up to 10 public PDFs, 10 MB cap, parses locally)
- **Live PDF sources**: NTA and UGC notice PDFs now enabled in
  `config/sources.json` with `"method": "pdf_links"`; keyword filters run
  against title + PDF text; extracted deadlines stored via `upsert_deadline`
- Extracted fields merged into opportunities by `entries.enrich()` — existing
  source-provided values are never overwritten

## Phase 7 — Internship Scout (ATS job boards)

- Live sources: 14 companies via Greenhouse + Ashby APIs (Figma, Vercel,
  Supabase, Ramp, Modal, Coinbase, Instacart, ...)
- 1,806 jobs scanned → 3 internships matched (Figma SWE Intern Winter 2027,
  Ramp Android Intern, Modal ML Research Intern)
- Run: `docker compose run --rm telegram-bot python -m src.discovery.internship_scout`

## Phase 6 — Fellowship Scout (first live source)

- **Source registry**: `config/sources.json` — add a source without code changes
  (name, url, method, trust_score, include/exclude patterns, enabled)
- **Live sources**: ICTS-TIFR announcements (official research lab, trust 95,
  HTML) + IIT Bombay news RSS (official university, trust 100) + NTA/UGC
  notice PDFs (official government, trust 100, `pdf_links` method)
- **Pipeline**: polite fetch (timeout/retries/backoff/per-domain delay) →
  RSS/Atom, HTML, or PDF parsing → Phase 8 extraction → keyword filter →
  Phase 5 schema → dedup insert → source linking + deadline upsert →
  execution logs
- **Trust**: trust ≥ 90 → `verification_status = official`; nothing ever
  marked verified without an official source
- Run: `docker compose run --rm telegram-bot python -m src.discovery.fellowship_scout`

## Phase 4 — Editable profile

- `/set <field> <value>` — edit university, branch, degree, current_year,
  graduation_year, country, skills, interests (no code changes needed)
- `/reset_profile` — restore defaults from `config/profile.json`
- `/profile` — view current profile
- Profile lives in the `users` table, bound to your Telegram chat ID

## Phase 3 — SQLite database

- `database/schema.sql` — 11 tables (opportunities, sources, deadlines,
  notifications, eligibility_results, scores, logs, errors, ...)
- Deduplication: unique `dedup_key` (normalized title|org|url|deadline)
- Portable SQL — swap to PostgreSQL later by replacing `src/db.get_connection()`
- DB file: `data/opportunity.db` (set via `DATABASE_PATH`)

## Phase 2 — Telegram bot

### One-time setup: create your bot token
1. In Telegram, open **@BotFather**
2. Send `/newbot`, pick a name (e.g. "Opportunity Scout") and a username ending in `bot`
3. Copy the token BotFather gives you (format: `123456789:AA...`)
4. `cp .env.example .env`, then set `TELEGRAM_BOT_TOKEN=...` in `.env`
5. Open your new bot in Telegram and press **Start** (bots can't message you first)
6. `docker compose up -d --build telegram-bot`

### Verify
- `docker compose ps` shows `opportunity-bot` as `Up`
- Send `/start`, `/profile`, `/opportunities` to the bot in Telegram

## Phase 1 — Docker + n8n

### Prerequisites (macOS)
- OrbStack (Docker engine + Compose): `brew install --cask orbstack`
- Ollama (later phases): `brew install ollama`

### Commands
```bash
cp .env.example .env          # optional; defaults work without it
docker compose up -d          # start n8n
docker compose ps             # check status
docker compose logs -f n8n    # follow logs
docker compose down           # stop (data persists in volume)
```

n8n UI: http://localhost:5678

### Verify
- `docker compose ps` shows `opportunity-n8n` as `healthy`
- Open http://localhost:5678 — you should see the n8n editor

### Notes
- Local-only config: `N8N_SECURE_COOKIE=false`, user management disabled.
  Do NOT expose this instance to the internet without adding auth + HTTPS.
- All data persists in the `n8n_data` volume.
- Keep the Mac awake (or use MODE B — an always-on Linux machine) for 24/7 operation.