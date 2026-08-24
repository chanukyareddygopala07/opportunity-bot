# AAWARA Security Model

This document describes the security controls actually implemented in this
repository (as of 2026-08-24). Anything not listed here is not implemented.

## Threat model highlights

- **Crawled web content is untrusted.** Opportunity text, URLs and metadata
  come from third parties and may be attacker-controlled.
- **LLM output is advisory only.** Model responses never overwrite
  deterministic pipeline fields (`eligibility_status`, `deadline`, etc.);
  they are stored in `ai_assessments` and displayed as advice.
- **Users can be attackers.** Anonymous endpoints are rate limited; admin is a
  role, not a name.

## Implemented controls

### Authentication & authorization
- Passwords hashed with scrypt (n=2^14), per-user random salt, constant-time compare.
- Sessions: 32-byte urlsafe tokens, DB-backed with expiry — **stored only as SHA-256 hashes** (`sessions.token_algo='sha256'`). Legacy plaintext rows upgrade in place on first use; a leaked stored hash cannot authenticate anyone.
- **RBAC**: `users.role` column (`user`|`admin`). Admin access = role check only. Reserved names (`admin`, `root`, `support`, …) cannot be registered; role is granted exclusively by `db.bootstrap_admin(ADMIN_USERNAME)` at startup when that named account exists.
- OAuth (Google/GitHub): state parameter validated (constant-time compare of cookie vs callback); email-based account linking **only** when the provider asserts the email is verified (GitHub primary verified email fetched from `/user/emails`).

### CSRF & browser hardening
- Stateless CSRF tokens: `HMAC(SECRET_KEY, "csrf:"+session_token)` for authenticated requests; anonymous double-submit cookie (`opp_csrf`) for login/register/report. Validated on every POST; machine calls with valid `X-Run-Token` exempt.
- Origin-vs-Host check retained as defense in depth.
- Cookies: `HttpOnly`, `SameSite=Lax`, `Secure` per policy — `COOKIE_SECURE=auto` (default) enables Secure automatically behind HTTPS/proxies; `force`/`never` override.
- Open-redirect protection on `next=` values (must be site-relative).
- Username-enumeration resistance on login (single generic error).

### Untrusted data handling
- **URL scheme allow-list** (`http`/`https`) enforced twice: at ingestion (`schema.normalize_opportunity` → `sanitize_url`) and at render time (`safe_url` template filter). `javascript:`/`data:`/`vbscript:` from crawled content cannot reach an `href`. Protocol-relative URLs normalized to https; control characters rejected.
- All SQL uses parameterized queries throughout the codebase.
- Jinja2 autoescape everywhere; the single `|safe` usage pre-escapes before inserting `<br>`.
- Sitemap XML built with explicit escaping and format-checked `lastmod`.
- Canonical/OG/sitemap URLs derive from `PUBLIC_BASE_URL` env when set, so hostile Host headers cannot poison them.

### API & abuse control
- FastAPI API: global per-IP throttle (120 req/min → 429 + Retry-After). Internal endpoints (`/crawl/jobs`, `/stats`, `/api/agents*`, `/api/agent-events|tasks`, `/api/pipeline/status`, `/crawl`) require `X-Run-Token`; opportunity browse/search/types/sources are public reads.
- Token comparisons are constant-time (`hmac.compare_digest`) in webhook, API and webapp.
- Anonymous report endpoints throttled per IP (5/hour) on both webapp and API.
- Login/register throttled (10 attempts / 10 min / IP).
- Pipeline trigger endpoints return generic errors — internal exception text never reaches callers.

### Privacy & LLM boundaries
- LLM prompts receive a **whitelisted profile projection** (`ai.safe_profile`): academic/career fields only. `password_hash`, `api_token_hash`, emails and OAuth ids never leave the perimeter (tested).
- Rudra chat history is user-scoped; messages truncated to 4000 chars; roles coerced so users cannot inject assistant turns.

## Not yet implemented (tracked in roadmap)

- Redis-backed rate limiting for multi-worker deployments.
- Prompt-injection scrubbing of crawled text before LLM calls (current mitigation: advisory-only storage caps blast radius).
- RAG grounding/citation enforcement for Rudra answers.
- Admin action audit log.
