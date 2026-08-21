# API Mapping — AAWARA

## Overview

This document maps all available backend endpoints to frontend services. The existing backend provides both Flask routes (SQLite-backed HTML pages) and FastAPI JSON endpoints. The frontend should prefer real backend data over mock data.

## Flask Route Mappings (HTML Pages)

| Frontend Page | Flask Route | Backend Data Source | Notes |
|---|---|---|---|
| Homepage | `GET /` | `db.list_opportunities()` + `deadlines.is_active()` + `helpers.score_items()` | Uses `g.user` for personalized scoring |
| Opportunity Listing | `GET /opportunities` | `db.list_opportunities()` + `helpers.filter_items()` | Supports: q, type, status, country, remote, verified, sort, paginate |
| Internships | `GET /internships` | `db.list_opportunities(type="internship")` | Category filter |
| Fellowships | `GET /fellowships` | `db.list_opportunities(type="fellowship")` | Category filter |
| Review Queue | `GET /review` | `db.list_opportunities(eligibility=["unclear"])` | Shows unclear eligibility roles |
| Top Picks | `GET /top` | `helpers.score_items(db.list_opportunities())` | Score-sorted with user profile |
| Urgent Deadlines | `GET /urgent` | Filter by `helpers.deadline_soon()` | Deadline-soon opportunities |
| Saved Opportunities | `GET /saved` | `db.list_bookmarks(user_id)` | Login required |
| Notifications | `GET /notifications` | `db.list_user_notifications(user_id)` | Login required, unread count |
| Profile | `GET /profile` | `db.get_user_by_id(user_id)` + form fields | Edit: country, citizenship, degree, year, CGPA, university, branch, skills, interests |
| Login | `GET/POST /login` | Credential verification via `auth.verify_password()` | Session cookie: `opp_session` |
| Register | `GET/POST /register` | Create user + profile seed | Email/password + optional OAuth |
| Logout | `POST /logout` | `auth.end_session()` | Clear session cookie |
| Detail Page | `GET /o/{id}` | `db.get_opportunity(opportunity_id)` + `helpers.score_item()` + `db.get_ai_assessment()` | Includes: score, status, reasons, missing, breakdown, ai assessment, bookmark, application |
| Apply Marked | `POST /o/{id}/apply` | `db.upsert_application(user_id, id, status="applied")` | Mark as applied with optional notes |
| Update Status | `POST /applications/{id}/status` | `db.upsert_application(user_id, id, status=...)` | Status: applied/interview/offer/rejected/withdrawn |
| Delete Application | `POST /applications/{id}/delete` | `db.remove_application(user_id, id)` | Remove application record |
| Report | `POST /o/{id}/report` | `db.add_report(opportunity_id, user_id, reason, notes)` | Adds to verification queue |
| Save Bookmark | `POST /o/{id}/save` | `db.add_bookmark(user_id, id)` | Add to saved list |
| Unsave Bookmark | `POST /o/{id}/unsave` | `db.remove_bookmark(user_id, id)` | Remove from saved list |
| Admin Dashboard | `GET /admin` | Various DB queries (counts, sources, jobs, reports, users, opportunities) | Admin required (username from env) |
| Toggle Source | `POST /admin/sources/{id}/toggle` | `db.set_source_enabled(id, enabled)` | Enable/disable source |
| Retry Job | `POST /admin/jobs/{id}/retry` | `db.retry_crawl_job(id)` | Reset crawl job to QUEUED |
| Resolve Report | `POST /admin/reports/{id}/resolve` | `db.resolve_report(id, resolution)` + possible `db.update_opportunity(status="closed")` | Resolution: accepted/rejected/ignored |
| Run Pipeline | `POST /admin/run` | `worker.run_pipeline()` | Trigger full discovery+crawl+extract pipeline |
| Robots.txt | `GET /robots.txt` | Static sitemap generation | Based on base URL + opportunity URLs |
| Sitemap.xml | `GET /sitemap.xml` | `db.list_opportunities()` + static URLs | Dynamic sitemap with lastmod from last_seen |
| Manifest.json | `GET /manifest.json` | Static JSON | PWA manifest |
| SW.js | `GET /sw.js` | Static service worker | Basic install/activate/fetch |
| Resources | `GET /resources` | `config/curated_links.json` | Groups of direct source links |
| Stats (Flask) | `GET /stats` | `webhook.stats_payload()` + DB logs/runs/jobs | System statistics |
| Rudra Chat | `GET /rudra` | `db.get_chat_history(user_id)` | AI chat history |
| Rudra Send | `POST /rudra/send` | `ai.chat_ask()` + history | Get AI reply |
| Rudra Stream | `POST /rudra/stream` | `ai.gemini_stream()` | SSE streaming |
| Rudra Clear | `POST /rudra/clear` | `db.clear_chat_history(user_id)` | Clear chat history |

## FastAPI JSON Endpoint Mappings

| Frontend Service | Endpoint | Method | Input Params | Output Data | Frontend Use |
|---|---|---|---|---|---|
| Health Check | `/health` | GET | — | `{"status": "ok", "time": "..."}` | App health monitoring |
| List Opportunities | `/opportunities` | GET | q, type, country, remote, verified_only, sort, limit | `{total, items: [_serialize(opp) for ...]}` | Opportunity discovery listing |
| Opportunity Detail | `/opportunities/{id}` | GET | — | `_serialize(opp)` | Detail page data |
| Structured Search | `/opportunities/search` | POST | body: SearchRequest (query, type, country, remote, verified_only, limit) | `{query, total, items}` | Natural language / advanced search |
| Opportunity Types | `/types` | GET | — | `{"types": [OPPORTUNITY_TYPES]}` | Filter dropdown population |
| Source Registry | `/sources` | GET | — | `{total, items: [{id, name, url, method, category, priority}]}` | Admin source management, filter options |
| Crawl Jobs | `/crawl/jobs` | GET | status, limit | `{total, items: [crawl_jobs]}` | Agent monitoring dashboard |
| System Stats | `/stats` | GET | — | Payload + logs + runs + jobs | Admin dashboard, footer stats |
| Trigger Crawl | `/crawl` | POST | body: Request, header: X-Run-Token | `{"ok": True, "summary": ...}` | Admin-initiated crawl |
| Report Incorrect | `/report/{id}` | POST | body: {reason, notes} | `{"ok": True, "report_id": id}` | Report UI integration |
| Eligible Types | N/A (use `/types`) | — | — | — | Filter type select population |

### SearchRequest Model (from api.py)

```python
class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=200)
    type: str | None = None
    country: str | None = None
    remote: bool | None = None
    verified_only: bool | None = None
    limit: int = Field(20, ge=1, le=100)
```

### _serialize Output Fields

```
id, title, organization, type, category, country, location, remote, deadline,
deadline_status, deadline_days_left, application_url, official_url, source_url,
eligibility_status, match_score, trust_score, trust_label, stipend, funding,
first_seen
```

## Frontend API Service Layer (Proposed)

All frontend API calls should go through a clean abstraction layer. Example structure:

```javascript
// src/frontend/api.js
const API_BASE = "/api"; // FastAPI prefix

export async function listOpportunities(filters = {}) {
  const params = new URLSearchParams();
  if (filters.query) params.append("q", filters.query);
  if (filters.type) params.append("type", filters.type);
  if (filters.country) params.append("country", filters.country);
  if (filters.remote !== undefined) params.append("remote", filters.remote ? "1" : "0");
  if (filters.verified_only) params.append("verified", "1");
  if (filters.sort) params.append("sort", filters.sort);
  if (filters.limit) params.append("limit", filters.limit);
  
  const resp = await fetch(`${API_BASE}/opportunities?${params}`);
  if (!resp.ok) throw new Error("Failed to load opportunities");
  return resp.json();
}

export async function getOpportunity(id) {
  const resp = await fetch(`/opportunities/${id}`); // Flask route
  if (!resp.ok) throw new Error("Opportunity not found");
  return resp.json();
}

// ... more services
```

### Preferred Data Flow

1. **Flask templates** — use `{{ url_for(...) }}` to render pages that already have `g.user` context and database queries
2. **FastAPI JSON** — use for programmatic data fetching (e.g., single-page app patterns, dashboard APIs)
3. **Direct database** — for templates that need `g.user` context (most Flask routes)

### API Integration Priorities

| Priority | Action | Reason |
|---|---|---|
| 1 | Reuse Flask routes + SQLite | Existing templates already work; no new backend needed |
| 2 | Use FastAPI `/opportunities` | Structured JSON, consistent serialization |
| 3 | Create adapter for missing endpoints | Document as TODO, implement when needed |
| 4 | Avoid mock data | Always prefer real backend data |

### Known API Gaps (Document, Don't Fake)

| Missing Endpoint | Proposed Frontend Adapter | Status |
|---|---|---|
| `/api/profile` | Pull profile from Flask `g.user` or `/profile` route | Documented — use existing Flask auth |
| `/api/recommendations` | Use `score_items()` + `score_breakdown()` from helpers | Scoring engine already exists in Python |
| `/api/saved` | Use Flask `/saved` route + bookmarks DB query | Bookmark system already functional |
| `/api/applications` | Use Flask `/applications` route + applications DB query | Application tracker already functional |
| `/api/agents` | Show "Agent status unavailable" placeholder | No agent API exists yet — document for Phase 15 |
| `/api/agent-tasks` | Show "Agent task metrics unavailable" | Same as above |
| `/api/admin/metrics` | Use Flask admin dashboard data | Admin already has overview section |

## Data Serialization Consistency

When calling multiple endpoints, normalize the opportunity shape. The `_serialize` function in `api.py` provides a consistent field set. Flask templates receive raw DB rows (via `row_to_opportunity`) which have additional JSON columns. When mixing data sources, ensure:

- `remote` and `hybrid` are booleans (not 0/1 integers)
- `trust_score` is an integer 0-100
- `match_score` is a number 0-100 or None
- `eligibility_status` is one of: eligible, likely_eligible, unclear, not_eligible, unknown
- `deadline` is ISO string or None
- `deadline_days_left` is integer (days) or None
- `trust_label` is derived from `trust_score` via `trust.trust_label()`

## Caching Strategy

- **Client-side**: Cache opportunity lists per filter combination (localStorage or sessionStorage)
- **Server-side**: Flask templates are already cached per route; add `Cache-Control` headers if needed
- **Avoid**: Continuously polling APIs without reason; use loading states instead
- **SSE/WebSocket**: Not currently available — use controlled polling if real-time needed

## Error Handling per Endpoint

| Endpoint | Loading | Empty | Error | Retry |
|---|---|---|---|---|
| `/opportunities` | Spinner/skeleton grid | "No opportunities found." with filter reset suggestion | "Unable to load opportunities. Try again." | Refresh button |
| `/opportunities/{id}` | Spinner + skeleton card | "No opportunity found." with back-link | "Opportunity not available." | Refresh + back |
| `/types` | Spinner | "No types available." | "Unable to load types." | — |
| `/sources` | Spinner | "No sources configured." | "Unable to load sources." | — |
| `/crawl/jobs` | Spinner | "No crawl jobs." | "Unable to load crawl status." | — |
| `/stats` | Spinner | "No stats available." | "Unable to load stats." | — |