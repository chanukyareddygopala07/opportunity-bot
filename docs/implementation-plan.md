# AAWARA — Implementation Plan

Rules that govern this plan (brief §54, §56):

- Work incrementally: inspect → plan → implement → test → inspect → fix →
  commit → continue.
- Never delete working functionality without a technical reason.
- Never present mock data as real. UNKNOWN over fabrication.
- Commit logically after each phase.
- Docs (current-architecture, current-features, problems,
  target-architecture) are the source of truth for why we do things.

## Phase A — Audit (DONE)

- [x] Inspect repo, routes, schema, crawlers, tests.
- [x] docs/current-architecture.md
- [x] docs/current-features.md
- [x] docs/problems.md
- [x] docs/target-architecture.md
- [x] docs/implementation-plan.md

## Phase B — Design system & landing experience (NEXT)

Delivers the visual identity from the design brief on the existing Flask
app. No rebuild; port 8080 preserved.

1. Design tokens: neon green (#00E676), bright green (#16FF7A), black
   #050505, white, gray #A0A0A0; fonts (Inter/Manrope + heavy weights);
   pill nav; oversized editorial typography; grid background.
2. base.html: floating pill navigation (AAWARA logo, DISCOVER,
   OPPORTUNITIES, FELLOWSHIPS, INTERNSHIPS, RESEARCH, HACKATHONS, LOGIN,
   SIGN UP), dark footer with links.
3. index.html (homepage): neon hero with technical grid, eyebrow, huge
   headline "Students / Builders / Dreamers" (Dreamers in black pill),
   floating content cards (asymmetric, rotated, hover float), CTA buttons,
   moving ticker strip, feature section (DISCOVER/MATCH/VERIFY/TRACK) on
   black, opportunity section (real DB data, verified badges, match %),
   natural-language search bar, category blocks, trust section (score from
   real verification data), profile CTA, final neon CTA, footer.
4. Extend style.css: keep existing classes working (cards, forms, chat,
   tables) under the new tokens; add reduced-motion support.
5. Tests: template smoke tests still pass; add homepage content assertions.
6. Commit: "design system + landing page".

## Phase C — Deadline engine + trust score (data layer, deterministic) — DONE

1. Deadline statuses: OPEN / CLOSING_SOON (≤30d) / CLOSED / UNKNOWN /
   NO_DEADLINE; timezone-aware (Asia/Kolkata default); never surface
   expired as active; computed column or view + denormalized field.
2. Trust score 0–100: official source +30, application URL valid +20,
   deadline verified +15, eligibility verified +15, recently crawled +10,
   duplicate-free +5, metadata consistent +5. Labels: Verified /
   Highly Verified / Needs Verification.
3. Data-quality tests: OPEN cannot have past deadline; every item has a
   source; application URLs valid; no fabricated fields.

## Phase D — PostgreSQL + FTS migration (behind abstraction)

1. Docker: postgres service; `db` layer gains a Postgres backend; keep
   SQLite fallback until migration verified.
2. Full schema from target-architecture (§3), tsvector search index.
3. Search: keyword + NL-to-filters with deterministic parser first, AI
   optional second (AIProvider abstraction).
4. Migrate data once; keep dual-run capability during transition.

## Phase E — Crawler router + job queue

1. Redis queue (or SQLite-backed queue first) with job states and priority.
2. Router: static → Crawlee, AI-friendly → Crawl4AI, complex → Firecrawl
   (self-hosted), JS-heavy → Playwright, interactive → Browser Use;
   record crawler_used per run.
3. Source registry in DB (migrate config/sources.json), source health
   surfaced in admin.
4. Crawl priority by deadline proximity / freshness / reports.

## Phase F — Structured extraction & 16 opportunity types

1. Extend opportunity_type enum + category/subcategory; structured
   eligibility (countries, degrees, years, branches, ages, experience).
2. Extraction engine emits structured fields; validation rejects
   fabrication; UNKNOWN for missing stipend/deadline/eligibility.

## Phase G — Verification pipeline v2

1. Official-source priority (official_url > source_url); alternative URLs
   on canonical; semantic deduplication (embedding-based, optional).
2. next_verification scheduling; verification priority bumps near
   deadlines.
3. Report incorrect information endpoint + admin review queue.

## Phase H — APIs (FastAPI) + admin — DONE

1. FastAPI app on :8000 with the API list from the brief; admin endpoints
   behind auth/roles; crawl trigger/retry; source enable/disable.
2. Admin dashboard (Flask UI) for opportunities, sources, crawl jobs,
   verification, duplicates, reports, users, health.

Implementation: `src/api.py` (FastAPI: health, opportunities
list/detail/search, types, sources, crawl jobs, stats, report, crawl
trigger behind X-Run-Token); Flask `/admin` (overview, sources toggle,
job retry, pending reports accept/ignore, users, opportunities, manual
pipeline run) gated by `ADMIN_USERNAME` (default "admin"); docker-compose
`api` service on 127.0.0.1:8000. Tests: `tests/test_admin_api.py`.

## Phase I — Profiles, matching, notifications, UX completeness — DONE (I-lite)

1. Student profiles v2 (preferences, countries, types, stipend, remote).
2. Recommendations: deterministic scoring first, AI-assisted second;
   "94% match" style output with reasons and missing requirements.
3. Notifications: new match, deadline approaching, saved-item changes,
   closed; channels: in-app + (optional) email/telegram; anti-spam caps.
4. Loading/empty/error/retry/success states; accessibility pass
   (focus-visible, ARIA, contrast, non-color status); responsive polish.

Implementation: in-app notifications (verified/official new opportunities
for every user, one per opp per user; deadline reminders for bookmarked
items, bucket-once) with `/notifications` page, mark-all-read, unread
bell badge; `/recently-viewed` via `user_views` table recorded on detail
views; empty states on saved/recent/list; skip link, focus-visible rings,
badge/unread styles, global `prefers-reduced-motion`. Profiles v2 and
email/telegram channels deferred (existing Telegram path intact).
Tests: `tests/test_phase_i_lite.py`.

## Phase J — Performance, security, final audit — DONE

1. Indexes, pagination, caching, bundle trimming, server-side rendering
   checks; avoid AI when deterministic suffices.
2. Security: input validation, CSRF, rate limiting, secret audit (CI job),
   authz tests.
3. SEO: sitemap, robots.txt, canonical URLs, OG/Twitter metadata.
4. End-to-end tests (Playwright optional), full pytest green, console-error
   check, accessibility checks.
5. Definition of Done checklist from brief §55 verified end-to-end.

Implementation: indexes (deadline_status, trust_score, type, last_seen —
verified via EXPLAIN QUERY PLAN); `/robots.txt` + `/sitemap.xml`;
canonical/OG/Twitter meta in base.html with detail-page overrides +
generated `static/og.png`; cross-origin POST guard (403) and failed-attempt
rate limiting on login/register (429); full suite green: 464 passed.
Tests: `tests/test_phase_j.py`.

---

## Sequencing notes

- Phase B is UI-only and safe to ship immediately (this session).
- Phases C–D are data-layer; E–F crawler; G–H trust+API; I–J product.
- Every phase keeps the app runnable at 127.0.0.1:8080.
- Commit after each phase; update docs as things change.