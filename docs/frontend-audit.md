# Frontend Audit — AAWARA

## Project Overview

AAWARA is a Python/Flask/Jinja-based opportunity discovery platform with AI integration, Rudra chat, multi-agent crawling architecture, and SQLite backend. The existing codebase provides working Flask routes, Jinja2 templates, a FastAPI JSON API, database models, scoring/eligibility engine, and crawler infrastructure.

## Existing Frontend Stack

- **Template engine**: Jinja2 (Flask)
- **CSS**: Custom styles in `src/webapp/static/style.css` (767 lines, design tokens, responsive rules)
- **JavaScript**: Minimal inline JS; most interactivity is form-submit driven
- **Layout**: Sticky pill-navbar, hero section, floating cards, ticker, feature grid, opportunity cards, trust section, profile CTA
- **Components**: Cards (opp-card, fcard, feature-card, cat-block, trust-grid, profile-cta, final-cta), tables, forms, badges, chips, tags
- **Responsive breakpoints**: 1080px, 760px, 460px media queries
- **Design tokens**: `--bg`, `--neon`, `--bright`, `--ink`, `--paper`, `--gray`, `--radius`, `--font`

## Existing Templates

| Template | Purpose | Key Features |
|---|---|---|
| `index.html` | Homepage | Hero with "Students Builders Dreamers", ticker, feature grid, opportunity grid, categories, trust section, profile CTA, final CTA |
| `detail.html` | Opportunity detail | Title, org, location, deadline, trust score, eligibility, facts table, description, requirements, skills, AI assessment, actions (save, apply, share, report) |
| `list.html` | Opportunity listing | Filter bar (query, type, status, country, remote, verified), pagination, item rows, empty state |
| `_items.html` | Card macro | Card with priority, title, score, meta, actions (details, apply) |
| `base.html` | Base layout | Pill navbar, user menu (login/logout, profile, saved, notifications, rudra, admin), footer, SEO meta |
| `admin.html` | Admin dashboard | Sections: overview, sources, jobs, reports, users, opportunities |
| `saved.html` | Saved opportunities | Bookmarked opportunities with scoring |
| `urgent.html` | Urgent deadlines | Deadline-soon opportunities |
| `top.html` | Top picks | Scored opportunities |
| `notifications.html` | User notifications | List with unread count |
| `profile.html` | User profile | Profile fields form (country, degree, year, CGPA, skills, interests) |
| `login.html` | Login form | Email/password auth |
| `register.html` | Registration form | Username/password with Google/GitHub OAuth options |
| `404.html` | Error page | Basic 404 |
| `stats.html` | System stats | Crawl logs, discovery runs, crawl jobs |
| `resources.html` | Direct sources | Curated links groups |
| `rudra.html` | AI chat history | Chat history with Rudra |
| `autofill.html` | Autofill extension | Token management |
| `resume.html` | Resume builder | Resume rendering |
| `tailor.html` | Resume tailor | Resume tailoring per opportunity |
| `items.html` | Not a template; `_items.html` is the macro file |

## Existing Flask Routes (Key Ones)

**Public routes**:
- `GET /` — homepage
- `GET /opportunities` — listing with filters (type, status, country, remote, verified, sort)
- `GET /internships`, `GET /fellowships` — category-filtered listings
- `GET /review` — review queue (unclear eligibility)
- `GET /top` — top-scored opportunities
- `GET /urgent` — deadline-soon opportunities
- `GET /saved` — saved bookmarks (login required)
- `GET /notifications` — user notifications
- `GET /profile` — profile editor (login required)
- `GET /login`, `POST /login` — email auth
- `GET /register`, `POST /register` — new user registration
- `GET /logout` — logout
- `GET /o/{id}` — opportunity detail
- `POST /o/{id}/save` — save bookmark (login required)
- `POST /o/{id}/unsave` — unsave bookmark (login required)
- `POST /o/{id}/report` — report incorrect information
- `POST /o/{id}/apply` — mark application (login required)
- `GET /applications` — application tracker (login required)
- `POST /applications/{id}/status` — update application status
- `POST /applications/{id}/delete` — remove application

**Admin routes**:
- `GET /admin` — admin dashboard (sections: overview, sources, jobs, reports, users, opportunities)
- `POST /admin/sources/<id>/toggle` — enable/disable source
- `POST /admin/jobs/<id>/retry` — retry crawl job
- `POST /admin/reports/<id>/resolve` — resolve report
- `POST /admin/run` — run pipeline

**API routes** (FastAPI, port 8000, but routes also registered in Flask via api.py patterns):
- `GET /health` — health check
- `GET /opportunities` — list with q, type, country, remote, verified_only, sort, limit
- `GET /opportunities/{id}` — detail by ID
- `POST /opportunities/search` — structured search (SearchRequest: query, type, country, remote, verified_only, limit)
- `GET /types` — opportunity type list
- `GET /sources` — source registry (sync + list enabled)
- `GET /crawl/jobs` — crawl job status
- `POST /crawl` — trigger crawl pipeline (X-Run-Token auth)
- `GET /stats` — system stats
- `POST /report/{id}` — report incorrect information
- `GET /api/opportunities` — JSON API (note: different prefix from Flask routes)

## Database Model (SQLite)

Key tables:
- `users` — username, password_hash, email, country, citizenship, degree, degree_level, current_year, cgpa, university, branch, resume_json, skills_json, interests_json, eligible_years_json, api_token_hash
- `opportunities` — title, organization, type, category, description, location, country, remote, hybrid, deadline, eligible_countries_json, eligible_degrees_json, eligible_years_json, eligible_branches_json, minimum_gpa, requirements_json, preferred_skills_json, stipend, currency, funding, application_url, official_url, source_url, source_type, verification_status, eligibility_status, match_score, trust_score, status, last_seen, first_seen, saved, deadline_status, next_verification, duplicate_of
- `sources` — name, organization, type (official_company, official_university, etc.), category, url, method, priority, enabled, trust_score, consecutive_failures, cooldown_until
- `bookmarks` — user_id + opportunity_id (saved)
- `applications` — user_id + opportunity_id + status + applied_at + updated_at + notes
- `verifications` — opportunity_id + status + link_status + message + checked_at
- `ai_assessments` — opportunity_id + verdict + reason + deadline_guess + confidence + model + created_at
- `crawl_jobs` — run_id, source_id, url, crawler, status, items_found, items_created, duplicates_found, error
- `discovery_runs` — full pipeline run logs
- `sources_health` — source health tracking
- `search_queries` — search query history

Key JSON columns:
- `eligible_countries_json`, `eligible_degrees_json`, `eligible_years_json`, `eligible_branches_json`
- `requirements_json`, `preferred_skills_json`, `resume_json`

## API Integration Map

### Flask Template → Backend

Most data flows through Flask routes that query the SQLite database directly. The `helpers.py` module provides filtering (`filter_items`), scoring (`score_items`, `score_breakdown`), pagination (`paginate`), and eligibility checks (`publishable`, `deadline_soon`, `deadline_days`).

### FastAPI JSON Endpoints

| Endpoint | Method | Params | Returns |
|---|---|---|---|
| `/health` | GET | — | `{"status": "ok", "time": "..."}` |
| `/opportunities` | GET | q, type, country, remote, verified_only, sort, limit | `{total, items: serialized opportunities}` |
| `/opportunities/{id}` | GET | — | Single serialized opportunity |
| `/opportunities/search` | POST | body: SearchRequest (query, type, country, remote, verified_only, limit) | `{query, total, items}` |
| `/types` | GET | — | `{"types": [OPPORTUNITY_TYPES]}` |
| `/sources` | GET | — | `{total, items: [source registry entries]}` |
| `/crawl/jobs` | GET | status, limit | `{total, items: [crawl jobs]}` |
| `/stats` | GET | — | System stats payload + logs + runs + jobs |

### Missing/API Gaps

- No dedicated `/api/profile` endpoint in FastAPI (profile data accessed via Flask `/profile` route)
- No `/api/recommendations` endpoint (scoring done client-side via `score_items` + `score_breakdown` in Flask)
- No `/api/saved` endpoint (bookmarks managed via Flask routes + SQLite)
- No `/api/applications` endpoint (applications managed via Flask routes + SQLite)
- No `/api/agents` endpoint (agent monitoring not exposed)
- No `/api/agent-tasks` endpoint
- No `/api/agent-events` endpoint
- No `/api/admin/metrics` endpoint

### Data Serialization (`api.py:_serialize`)

Opportunities from the API return these fields:
```
id, title, organization, type, category, country, location, remote, deadline,
deadline_status, deadline_days_left, application_url, official_url, source_url,
eligibility_status, match_score, trust_score, trust_label, stipend, funding,
first_seen
```

### Authentication

- Flask session-based (cookie: `opp_session`)
- `_login_required` decorator checks `g.user`
- Password: scrypt hashlib (`hashlib.scrypt` with n=2^14, r=8, p=1)
- OAuth: Google + GitHub (configured via env vars)
- API token: stored as `api_token_hash` on users table

## Frontend Gaps & Opportunities

### What exists and can be reused:

1. **Database with 12 opportunities** — real data available
2. **42 source registry** — real sources with priorities and trust scores
3. **Scoring/eligibility engine** — `scoring.py` and `helpers.py` provide deterministic match scores and eligibility evaluation
4. **FastAPI JSON API** — read-only opportunities, types, sources, crawl jobs, stats
5. **Template structure** — all major pages already have Jinja2 templates
6. **CSS design system** — tokens, colors, typography, responsive breakpoints already defined
7. **Pill navigation** — working in base.html
8. **User auth system** — login/register/logout with session cookies
9. **Application tracking** — applications table + status flow (applied → interview → offer/rejected)
10. **Saved/bookmark system** — bookmarks table + save/unsave flow
11. **Report incorrect information** — report flow + DB verification table
12. **Rudra AI chat** — SSE streaming + Gemini/Ollama integration

### What needs to be built:

1. **New AAWARA design system** — neon green/black/white, oversized typography, technical grid, floating cards, asymmetric layouts, pill navigation
2. **Homepage hero** — with "Students Builders Dreamers" and black highlight rect
3. **Floating opportunity cards** — with real backend data
4. **Search bar** — natural language input connecting to backend
5. **Opportunity discovery page** — filtered, sorted, paginated with real data
6. **Opportunity detail page** — premium layout with all fields, actions
7. **Filter interface** — modern UI with connect to backend APIs
8. **Student dashboard** — overview, recommended, saved, applications, profile
9. **Application tracker** — visual status pipeline
10. **Agent monitoring dashboard** — 16 agent cards with real metrics (or "unavailable" placeholders)
11. **Admin dashboard** — sources, crawlers, verification queue, users, system health
12. **Natural language search UI** — "What are you looking for?" with examples
13. **Moving ticker** — smooth infinite horizontal animation
14. **Trust/verification UI** — VERIFIED/HIGHLY VERIFIED/NEEDS VERIFICATION badges
15. **SEO optimization** — proper title, description, Open Graph, canonical URLs, sitemap, robots.txt
16. **Error/loading/empty/retry states** — for all major components

### API Integration Strategy

**Priority 1**: Reuse existing Flask routes + SQLite data — no new backend needed for basic pages
**Priority 2**: Use FastAPI JSON endpoints where they provide structured data
**Priority 3**: Create thin frontend adapter layers for missing endpoints, documented as TODO
**Priority 4**: Build backend adapters only if absolutely necessary (document and mark as placeholder)

Key principle: **Never create fake/mock opportunity data when real backend data is available.** All UI components must connect to actual `db.list_opportunities()`, FastAPI `/opportunities`, or `/api/opportunities` endpoints.

## Next Steps

1. Create docs/api-map.md — detailed endpoint mapping
2. Create docs/ui-architecture.md — component architecture
3. Redesign CSS for AAWARA visual identity
4. Build homepage with hero, floating cards, ticker
5. Build opportunity discovery page with filters
6. Build opportunity detail page
7. Build student dashboard
8. Build agent/administrative dashboards
9. Integrate all real APIs, document gaps
10. Test all flows