# AAWARA — Current Features

Inventory of what works today (verified by tests + live checks).

## 1. Discovery

- 24/7 scheduled discovery via n8n (every 2h) → POST /run.
- Two named agents:
  - **Arjun** (internship_scout) — internships/jobs, ATS APIs.
  - **Vidya** (fellowship_scout) — fellowships/scholarships/research.
- 50 sources in registry (36 enabled): Greenhouse, Ashby, Lever, generic
  JSON APIs, YC, Spotify, IISc, IIT Bombay, Mitacs, DAAD, plus RSS/HTML
  feeds; 4 curated link groups (India internships, global boards,
  fellowships & research official portals, IIT/IISc/IISER/NIT research).
- Per-run observability in discovery_runs (gates, counts, errors, HTTP
  status, response time).
- Ethical crawling: robots.txt checks, rate limit per source, timeouts,
  retries, backoff, cooldown, circuit breaker, source health tracking.

## 2. Eligibility engine (v2)

- CGPA parsing (10-point, %, percent → GPA conversions), CGPA threshold
  eligibility; missing CGPA is neutral (not disqualifying).
- Citizenship / work-authorization exclusion handling, REU nuance
  (US-citizens-only → not_eligible; international-welcome → eligible;
  silent → unclear).
- Score breakdown: eligibility %, career fit %, overall %; reasons +
  missing-information lists.

## 3. Web app

- Aawara-branded UI (dark, accent #5b8cff, saffron).
- Pages: home (fresh + matches + urgent), opportunities list with filters
  (type, eligibility, search), Arjun/Vidya category pages, top, urgent
  (deadline watch), review queue, saved, detail with score/breakdown,
  stats (incl. per-source run table by bot), resources (direct sources),
  profile, auth (register/login/logout/OAuth), 404.
- Deadline states shown on cards ("days left"), urgent list sorted by
  deadline proximity.
- PWA: manifest + service worker registration.

## 4. Rudra (AI career guide)

- Chat UI with SSE streaming (token-by-token, typing indicator).
- Providers: OpenAI → Gemini → Ollama, graceful offline fallback message.
- Advisory-only guardrails (no invented facts, no dishonest advice, no
  sensitive data); profile context injected (facts locked).
- History persisted (chat_messages), clear-chat action.

## 5. Resume system

- Fact-locked resume builder from profile + JSON sections (education,
  experience, projects, awards, contact).
- JD-aware tailoring — reorders matched skills, never invents; audit notes
  list what changed.
- Downloads: .txt (ATS) and .pdf (reportlab).

## 6. Autofill Chrome extension (MV3)

- Per-user API token (hashed in DB), /api/autofill/resume endpoint.
- Content script fills only empty fields (name/email/phone/LinkedIn/
  GitHub/education/skills/interests), heuristic label matching, works on
  generic + Lever/Greenhouse/Ashby forms.

## 7. Applications tracker

- Mark applied on an opportunity; statuses: applied, interview, offer,
  rejected, withdrawn; notes; deadline watch section; counts by status.

## 8. Stats & observability

- /stats: last pipeline run, Arjun/Vidya per-source run table, execution
  logs (25 latest).
- discovery_runs + source_health + system_errors + execution_logs tables.

## 9. Auth & security posture

- Session cookies (random tokens, expiry), scrypt password hashing.
- Google + GitHub OAuth.
- Per-user API tokens hashed; secrets only in .env (gitignored).
- Pipeline hook guarded by RUN_TOKEN (X-Run-Token).
- No secrets committed (verified by git audit).

## 10. Tests

- 356 pytest tests: db, schema, scoring, eligibility v2, discovery,
  internship/fellowship scouts, ATS adapters, extraction, PDF, dedupe,
  verification, ai (incl. Gemini mocks), Rudra streaming, resume, autofill
  API, applications, webapp routes, auth, oauth, worker/webhook.