# AAWARA — Problems & Gaps

Identified during the audit (2026-08-20). Ordered by impact.

## Critical / correctness

1. **SQLite, not PostgreSQL.** Single-writer SQLite file (data/opportunity.db)
   limits concurrency, full-text search, and scale. The target architecture
   requires PostgreSQL (sections 5, 9 of the brief).
2. **No separate API layer.** The Flask web app is the only interface. The
   brief requires clean REST APIs (GET /opportunities, /search, /match,
   /recommendations, admin APIs).
3. **No background job/queue system.** The pipeline runs synchronously in the
   web process (or via a webhook call from n8n). No Redis, no job states
   (QUEUED/RUNNING/FAILED/RETRYING).
4. **No crawler router.** All sources use the same fetch path; there is no
   crawler selection (Crawlee/Crawl4AI/Firecrawl/Playwright/Browser Use) and
   no per-crawl `crawler_used` recording.
5. **Deadline engine missing.** No computed per-opportunity deadline status
   (OPEN / CLOSING_SOON / CLOSED / UNKNOWN / NO_DEADLINE); expired items can
   still be shown as active. Date handling is not consistently timezone-aware.

## Trust & data quality

6. **Trust score not implemented.** No 0–100 trust score (official source,
   application URL valid, deadline verified, eligibility verified, recently
   crawled, duplicate-free, metadata consistency).
7. **Verification is link-level only.** No official-source priority logic
   (official_url > aggregator), no next_verification scheduling, no
   verification-priority increase when deadlines approach.
8. **Deduplication is basic.** Normalized-title/URL similarity only; no
   semantic similarity, no canonical opportunity merging with alternative
   source URLs.
9. **Eligibility/requirements not structured.** Requirements are free text
   (requirements_json), not structured fields (eligible_countries, degrees,
   years, branches, ages, experience).
10. **Freshness fields missing.** last_crawled / last_verified /
    next_verification / source_last_seen are not first-class columns on
    opportunities (only inferred from logs).

## Features required by the brief but absent

11. **Natural-language search** (section 14) — only keyword filters today.
12. **Full-text / semantic search** — no FTS index, no vector search.
13. **Rich filters** — no state/city/country/type/field/stipend/funding/
    duration/verified-only filters.
14. **Support for 16 opportunity types** — currently internships +
    fellowships (+ implicit categories); no hackathons, scholarships,
    grants, workshops, conferences, exchange, entrepreneurship, volunteering.
15. **Report incorrect information** — absent.
16. **Admin dashboard** — absent (opportunities/sources/jobs/verification/
    duplicates/reports/users/health).
17. **Notifications** (email/telegram/web) for new matches, deadline changes,
    saved-item changes — only a legacy notifications table, no channels.
18. **Recently viewed** tracking — absent.
19. **Collections** in saved system — absent.
20. **Trending opportunities** — absent.
21. **SEO** — no sitemap, robots.txt, canonical URLs, OG/Twitter metadata.

## Design / UX

22. **Visual identity does not match the brief.** Current UI is a functional
    dark dashboard; the brief requires a neon-green editorial/creative
    experience (hero, floating cards, ticker, oversized typography).
23. **No loading/error/empty/retry states** on most pages (server-rendered,
    no client-side states).
24. **Accessibility incomplete** — no focus-visible styling, minimal ARIA,
    color-only status cues in places.
25. **Mobile nav** is a wrapping pill row; needs a compact app-like treatment.

## Architecture / engineering

26. **Monolith coupling**: webapp ↔ pipeline ↔ AI in one process; no module
    boundaries for an API-first future.
27. **No CI/CD**, no lint/type tooling beyond pytest.
28. **No structured logging** (JSON), no metrics endpoint beyond /health and
    /stats.json.
29. **Config sprawl**: sources.json + curated_links.json + profile.json in
    files — the brief wants a DB-backed source registry.
30. **Crawl priority** is static; no priority queue (deadline proximity,
    source freshness, reports).
31. **Frontend has no framework** — rebuilding as Next.js is optional and
    must be weighed against the working Jinja app (brief section 1: do not
    blindly rebuild).

## Known minor issues (from live checks)

32. Default seed user (from config/profile.json) exists in DB with no
    username — fine for legacy bot flows but confusing in the new UI.
33. `.DS_Store` ignore rule needed a newline fix in .gitignore.
34. Some sources disabled after 403s/login-gates (EURAXESS, AICTE, MoSPI,
    NITI Aayog, UGC, INSPIRE, Commonwealth, NSP, NSF REU) — need re-probe
    strategy with the new crawler router.

## Non-goals (explicit)

- scrcpy / Android automation — out of scope unless needed later.
- No paid APIs; everything self-hostable (Firecrawl only self-hosted).