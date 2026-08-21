# UI Architecture — AAWARA

## Design Principles

### Visual Identity
- **Primary colors**: Neon green (`#00e676`), Black (`#050505`), White (`#ffffff`)
- **Accent**: Bright green (`#16ff7a`), Saffron (`#16ff7a`)
- **Background**: Paper white (`#ffffff`) on dark (`#050505`)
- **Text**: Ink (`#050505`) on paper (`#ffffff`), Muted (`#a0a0a0`)
- **Neon glow**: `rgba(0, 230, 118, 0.10)` to `rgba(0, 230, 118, 0.12)`

### Design Directions (from prompt)
- Experimental / modern experimental design websites
- NOT a generic job portal
- Neon green + black + white
- Oversized typography
- Technical grid backgrounds
- Floating opportunity cards
- Asymmetric layouts
- Rounded pill navigation
- Editorial layouts
- Large typography
- Smooth animations
- Premium spacing
- Subtle parallax
- High contrast
- Modern geometric typography

### Feeling
- Creative-tech platform + AI product + Student opportunity network + Premium editorial website
- Original, must NOT copy existing websites

## Component Architecture

### 1. Navigation (Pill Navigation)
- **Rounded pill style** with black background and neon green text
- **Brand**: AAWARA (left-aligned, neon dot accent)
- **Tabs**: DISCOVER, OPPORTUNITIES, FELLOWSHIPS, INTERNSHIPS, RESEARCH, HACKATHONS
- **User menu**: LOGIN / SIGN UP → (right-aligned)
- **Responsive**: Collapses to hamburger on mobile; tablet shows reduced items

### 2. Hero Section (Homepage)
- **Premium hero** with large asymmetric composition
- **Headline**: "THE OPPORTUNITY NETWORK FOR STUDENTS"
- **Sub-headline**: Students / Builders / **Dreamers** (final word in black rounded rect with white text)
- **Subtitle**: "Discover opportunities, build your future, and find what's next."
- **Primary CTA**: EXPLORE OPPORTUNITIES → (neon green button)
- **Secondary CTA**: BUILD MY PROFILE (border button)
- **Floating cards** surround hero: internships, fellowships, research, startups, universities, hackathons, scholarships
- **Connect to backend**: Floating cards use real opportunity data from `db.list_opportunities()`

### 3. Moving Ticker
- **Large editorial ticker** at top of page
- **Content**: INTERNSHIPS ✦ FELLOWSHIPS ✦ RESEARCH ✦ SCHOLARSHIPS ✦ HACKATHONS ✦ STARTUPS ✦ UNIVERSITIES ✦ (repeats)
- **Animation**: Smooth infinite horizontal scroll (30s linear infinite)
- **Colors**: Black background, neon green text, star ✦ in neon green
- **Responsive**: Reduces on mobile; may switch to vertical stack

### 4. Search Bar (Discovery Page)
- **Large search bar** with placeholder: "What are you looking for?"
- **Supports natural language**: "AI internships for second year students", "Fully funded research programs in USA", "IIT fellowships", "Remote internships with no experience", "Scholarships for Indian students"
- **Connects to**: Natural Language Search Agent → backend search
- **Example chips** below or inside: AI, Remote, Fully Funded, IIT, Scholarships
- **Input**: "What opportunity are you looking for?"
- **Search trigger**: Enter key or search button

### 5. Opportunity Discovery Page
- **Grid layout** with asymmetric card sizing
- **Each card shows**:
  - Title (large, truncated with ellipsis)
  - Organization (badge/line)
  - Logo if available (avatar/image)
  - Opportunity type chip (internship/fellowship/research/etc.)
  - Location + Remote/Hybrid indicator
  - Deadline (with countdown if active)
  - Stipend/Funding (if available)
  - Eligibility status tag
  - Verification status badge (VERIFIED/HIGHLY VERIFIED/NEEDS VERIFICATION)
  - Match score percentage
  - Last verified date
- **Actions per card**:
  - VIEW OPPORTUNITY → (detail page)
  - SAVE → (toggle bookmark)
  - SHARE → (share modal/link)
  - REPORT → (report incorrect information)
- **Empty state**: "No opportunities found." with filter reset CTA
- **Loading**: Skeleton grid with premium styling
- **Error**: "Unable to load opportunities." with retry button

### 6. Filter Interface (Modern UI)
- **Filters panel** (sidebar or dropdown)
- **Filter options**:
  - Country (dropdown with all countries from backend)
  - State/Region
  - Opportunity type (checkboxes: internship, fellowship, research, etc.)
  - Field/AI/ML, Computer Science, Data Science, etc.
  - Education level (Undergraduate, Graduate, etc.)
  - Year (1st–5th year)
  - Branch/Department (CSE, ECE, Mechanical, etc.)
  - Remote (toggle)
  - Deadline (range picker: Open, Closing Soon, Within 30 days)
  - Funding (Fully funded, Stipend, Unpaid, Any)
  - Stipend range (₹/month range)
  - Experience (0-2 years, 2-5 years, Any)
  - Verified only (toggle)
- **Sorting**: Relevance (default), Newest, Deadline, Recently verified, Best match
- **Connects to**: Backend `helpers.filter_items()` + FastAPI `/opportunities`
- **Applied filters**: Show active filters with remove chips
- **Responsive**: Collapses to collapsible sections on mobile; checkboxes become stacked

### 7. Opportunity Detail Page
- **Premium layout** with editorial styling
- **Top section**:
  - Title (large typography)
  - Organization name
  - Location + Remote/Hybrid badge
  - Type chip
  - Deadline countdown (CLOSING IN 8 DAYS or CLOSED)
  - Trust score badge (VERIFIED / HIGHLY VERIFIED / NEEDS VERIFICATION)
- **Left column** (or accordion sections):
  - Eligibility (with eligibility_pct and reasons)
  - Description (truncated, expandable)
  - Skills (chips)
  - Stipend (with currency)
  - Funding type
  - Duration
  - Important dates (application opening, result date)
  - Application process steps
  - Official source link
  - Verification status details
  - Last verified timestamp
  - Trust score (0-100 bar)
  - Match percentage (if user profile exists)
- **Right column** or bottom section:
  - Actions:
    - APPLY NOW → (visually dominant button, primary CTA)
    - SAVE → (toggle bookmark)
    - SHARE → (share modal)
    - REPORT INCORRECT INFORMATION → (report form)
  - Similar opportunities (3-4 cards below)
  - AI match explanation (if profile exists):
    ```
    94% MATCH
    ✓ AI/ML relevant
    ✓ Undergraduate eligible
    ✓ Second-year students accepted
    ✓ Indian students eligible
    ○ Research experience preferred
    ```
- **Empty state**: When no details available, show "Opportunity details loading..."
- **Error**: "Unable to load opportunity details." with back button

### 8. Student Dashboard
- **Overview section**:
  - GOOD MORNING [Name] (or time-based greeting)
  - "12 new opportunities match your profile."
  - "94% AI MATCH"
  - Featured opportunity card with "Closing in 8 days" + VIEW →
- **Recommended section**:
  - Grid of 3-4 opportunities matched to profile
  - Each with match score and eligibility badge
- **Saved section**:
  - Bookmarked opportunities (same card style as discovery)
  - Quick actions: SAVE / UNSAVE
- **Applications section**:
  - Application tracker visual: SAVED ↓ INTERESTED ↓ APPLIED ↓ ASSESSMENT ↓ INTERVIEW ↓ ACCEPTED/REJECTED
  - List of applications with status + deadline + notes
  - Update status form per application
- **Closing Soon section**:
  - Opportunities with deadlines < 14 days
  - Countdown per opportunity
- **Recently Viewed**:
  - Last 5-8 viewed opportunities
  - Quick re-access
- **Profile section**:
  - Edit profile link
  - Quick stats: degrees, years, skills summary
- **Preferences**:
  - Saved filter preferences
  - Notification preferences
- **Connects to**: Backend `db.list_opportunities()` with user profile scoring, `db.list_bookmarks()`, `db.list_applications()`

### 9. Application Tracker
- **Visual pipeline**:
  ```
  SAVED → ↓ → INTERESTED → ↓ → APPLIED → ↓ → ASSESSMENT → ↓ → INTERVIEW → ↓ → ACCEPTED / REJECTED
  ```
- **Status chips** per stage with current status highlighted
- **User can**:
  - Add notes per stage
  - Update status (click to advance/change)
  - Set deadline reminders
  - View dates per stage
- **Connects to**: Backend `applications` table + `db.upsert_application()` + `db.remove_application()`

### 10. Agent Monitoring Dashboard
- **16 agent cards** corresponding to real agents:
  1. DISCOVERY AGENT
  2. CRAWLER AGENT
  3. EXTRACTION AGENT
  4. CLASSIFICATION AGENT
  5. ELIGIBILITY AGENT
  6. DEADLINE AGENT
  7. SOURCE VERIFICATION AGENT
  8. DUPLICATE AGENT
  9. QUALITY CONTROL AGENT
  10. TRUST SCORE AGENT
  11. RECOMMENDATION AGENT
  12. NATURAL LANGUAGE SEARCH AGENT
  13. FRESHNESS AGENT
  14. CHANGE DETECTION AGENT
  15. USER SUPPORT AGENT
  16. APPLICATION ASSISTANT
- **Each card shows**:
  - Agent icon / category badge
  - Status: ACTIVE / IDLE / OFFLINE (from backend)
  - Primary metric (sources discovered, pages crawled, records extracted, etc.)
  - Secondary metric
  - Health indicator: HEALTHY / DEGRADED / FAILING / OFFLINE
  - Last activity timestamp
  - Error count
- **Connects to**: Backend DB metrics (or "Agent status unavailable" when no data)
- **Agent pipeline visualization**:
  ```
  DISCOVERY ↓ CRAWL ↓ EXTRACT ↓ CLASSIFY ↓ VERIFY ↓ DEDUPLICATE ↓ QUALITY CONTROL ↓ TRUST SCORE ↓ DATABASE
  ```
- **Each step shows**: task state (QUEUED/RUNNING/COMPLETED/FAILED)
- **Detail page** per agent (click card):
  - Current task
  - Recent tasks (table)
  - Success rate, failure rate
  - Average duration
  - Average confidence
  - Input/output examples
  - Errors
  - Recent events
  - Retry count
  - Queue size
  - Performance chart (over time)
  - Admin actions: Pause, Resume, Retry failed, Run test, Clear queue
- **Only authorized users** (admin) can control agents

### 11. Admin Dashboard
- **Overview**:
  - Total opportunities, sources, users, queue stats
  - System health metrics
- **Opportunities**:
  - Search/filter admin opportunities
  - View all opportunities with full details
  - Edit: verify, reject, merge duplicate, mark closed, re-crawl
  - View evidence per opportunity
  - View agent history
- **Sources**:
  - Source health table:
    | Source | Status | Last crawl | Success rate | Opportunities found | Failures |
    |---|---|---|---|---|---|
  - Crawler jobs:
    | Queued | Running | Completed | Failed | Retrying |
  - Add/Edit/Disable/Enable source
  - View history per source
- **Agents**:
  - All 16 agent cards (read-only for non-admin)
  - Agent task queue
  - Event log
- **Verification Queue**:
  - Pending reviews
  - Action buttons: APPROVE, REJECT, EDIT, MERGE, RECRAWL, MARK_VERIFIED
- **Duplicates**:
  - Duplicate groups
  - Merge/split actions
- **Reports**:
  - Pending reports list
  - Resolution actions
- **Users**:
  - User list with roles
  - Profile management
  - Account status
- **System Health**:
  - Database status
  - Redis/caching status (if available)
  - AI provider status
  - Crawler system status
  - Error logs
  - Performance metrics

### 12. Trust / Verification UI
- **Verification badges** per opportunity:
  - VERIFIED (green) — 75-89 trust score
  - HIGHLY VERIFIED (bright green) — 90-100 trust score
  - NEEDS VERIFICATION (orange) — 0-49 trust score
- **Never visually claim** something is verified unless backend says it is verified
- **Trust score display**: `{{ trust_score }}/100` with color-coded tag
- **Verification details** (expandable):
  - Official source ✓
  - Last verified: [date]
  - Deadline verified ✓ / ✗
  - Eligibility verified ✓ / ✗
  - Application link verified ✓ / ✗
- **Connects to**: Backend `verifications` table + `trust.trust_label()` + `deadlines.status()`

### 13. Profile Page
- **Profile overview** with current fields
- **Editable fields**:
  - Country, citizenship
  - Degree (Btech, Mtech, BSc, MSc, etc.)
  - Degree level / current year (1st–5th)
  - CGPA (0-10 scale)
  - University
  - Branch/Department
  - Skills (comma-separated tags)
  - Interests (comma-separated tags)
  - Eligible years (range)
  - Eligible branches (list)
  - Preferred opportunities (filter criteria)
  - Allow preferences (what opportunities user wants)
- **Connects to**: Backend `users` table + `db.update_user_fields()`
- **Profile CTA** on homepage: "Make AAWARA yours." + "EDIT MY PROFILE →"

### 14. Saved Opportunities Page
- **Grid of saved/bookmarked opportunities**
- **Each card**: Same as discovery card but with UNSAVE action
- **Quick stats**: Number saved, matches your profile %
- **Connects to**: Backend `bookmarks` table + `db.list_bookmarks(user_id)`

### 15. Natural Language Search UI
- **Large search input**: "What are you looking for?"
- **Example prompts** (click-to-fill):
  - "AI internships for second year students"
  - "Fully funded research programs in USA"
  - "IIT fellowships"
  - "Remote internships with no experience"
  - "Scholarships for Indian students"
- **Recent searches** chip list
- **Connects to**: Backend `helpers.filter_items()` or FastAPI `/opportunities/search`

## Responsive Design Breakpoints

| Device | Layout Changes |
|---|---|
| **Desktop (1400+px)** | Full asymmetric layouts, floating cards visible, ticker full width, multi-column filters, 3-column grids |
| **Tablet (760-1399px)** | Reduced floating cards (opacity 0.85), single/two column grids, collapsible filter sections, pill nav reduces to essentials |
| **Mobile (<760px)** | No horizontal overflow, readable typography (clamped sizes), touch-friendly buttons (44px min), collapsible filters (accordion), vertical stack cards, hamburger nav, ticker may switch to vertical list |
| **Max-width 460px** | Footer grid 1col, hero-cta buttons full-width, profile CTA full-width |

## Accessibility (a11y)

- **Semantic HTML**: `<header>`, `<nav>`, `<main>`, `<section>`, `<article>`, `<aside>`, `<footer>`
- **Keyboard navigation**: Tab order logical, focus-visible styles (3px neon green outline)
- **Focus states**: `a:focus-visible, button:focus-visible, input:focus-visible { outline: 3px solid var(--neon); }`
- **Screen reader**: ARIA labels on interactive elements, descriptive alt text for images
- **Contrast**: Minimum 4.5:1 for normal text, 3:1 for large text (neon on black meets this)
- **Resize text**: Support up to 200% zoom without breaking layout
- **Reduced motion**: `prefers-reduced-motion: reduce` disables all non-essential animations (ticker, float, pulse)
- **Forms**: Labels associated with inputs, error announcement, clear instructions
- **Skip link**: `#main` anchor at top of body

## SEO

### Global Site Meta (base.html)
- **Title**: `AAWARA — Discover Opportunities. Explore What's Next.`
- **Description**: `AAWARA — Discover opportunities, fellowships, scholarships and research programs for Indian students. Verified opportunities, AI-powered matching.`
- **Keywords**: `internships, fellowships, scholarships, research programs, opportunities, Indian students, AI-powered`
- **Open Graph**:
  - `og:title`: `AAWARA — Discover Opportunities. Explore What's Next.`
  - `og:description`: Same as above
  - `og:type`: `website`
  - `og:url`: Canonical URL per page
  - `og:image`: `/static/og.png`
  - `og:site_name`: `AAWARA`
- **Twitter**:
  - `twitter:card`: `summary_large_image`
  - `twitter:title`: `AAWARA`
  - `twitter:description`: `Discover opportunities, fellowships, scholarships and research programs for Indian students.`
  - `twitter:image`: `/static/og.png`
- **Per-page blocks** in each template override og_title, og_description, og_url, og_image, tw_title, tw_description

### Page-Specific SEO

| Page | Title | Description | OG |
|---|---|---|---|
| Homepage | `AAWARA — Discover Opportunities. Explore What's Next.` | `AAWARA — the opportunity network for students.` | Same |
| Discovery | `{{kind | title}} — AAWARA` | `Filter {{kind | lowercase}} opportunities on AAWARA.` | — |
| Detail | `{{opp.title}} — {{opp.organization | default('opportunity') }} — AAWARA` | `{{opp.title }} at {{opp.organization}}. Apply or save on AAWARA.` | — |
| Dashboard | `Your Dashboard — AAWARA` | `Your opportunity dashboard with matches and applications.` | — |
| Profile | `My Profile — AAWARA` | `Your profile and preferences on AAWARA.` | — |
| Admin | `AAWARA Admin — Overview` | `AAWARA administration dashboard.` | — |

### Sitemap & Robots
- **sitemap.xml** — generated dynamically (already exists in Flask routes)
- **robots.txt** — already exists, allows all, points to sitemap
- **Canonical URLs** — each page has `<link rel="canonical">`

## Error States (All Components)

Every major component needs these 4 states:

| State | Example |
|---|---|
| **Loading** | Skeleton grid, spinner, "Loading opportunities..." |
| **Empty** | "No opportunities found." with suggestion to adjust filters |
| **Error** | "Unable to load opportunities. Retry?" with refresh button |
| **Success** | Grid of opportunity cards with full data |

### Opportunity Discovery Empty State
> "No opportunities match your search. Try adjusting filters, broadening your search, or clearing the filters below."

### Opportunity Detail Empty State
> "Opportunity details are temporarily unavailable. Return to discovery."

### Agent Dashboard Unavailable
> "Agent status unavailable. This dashboard requires agent task data from the backend."

### Search No Results
> "No opportunities match "AI internships for second year students". Try broadening your search or removing filters."

## Performance Optimizations

- **Image lazy loading**: `loading="lazy"` on all opportunity card images
- **CSS**: Tokens-driven, minimal critical CSS above the fold
- **JS**: Minimal; most interactivity is form-submit driven (no heavy frameworks)
- **API caching**: Flask templates already have per-route caching; add `Cache-Control` headers for API calls
- **Pagination**: 12 items per page (PAGE_SIZE = 12 in helpers.py)
- **Avoid**: Continuously polling APIs unnecessarily; use loading states instead
- **SSE/WebSocket**: Not currently available — if added later, use for real-time agent notifications
- **Bundle size**: Keep CSS modular; avoid adding heavy JS frameworks

## Animation Guidelines

### Allowed Animations
- **Text reveal** (fade-in, typewriter)
- **Card entrance** (staggered on page load, respect prefers-reduced-motion)
- **Hover movement** (subtle lift, shadow change, color shift)
- **Image zoom** (on hover, container-constrained)
- **Subtle floating cards** (vertical float, 6.5s ease-in-out infinite, reduced on media query)
- **Ticker animation** (30s linear infinite horizontal scroll, can stack on mobile)
- **Smooth page transitions** (fade, 300ms max)

### Disabled with `prefers-reduced-motion`
All animations, transitions, and keyframes are wrapped in `@media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }`

### Animation Quality
- Use `transform: translate()` instead of `top/left` for GPU-accelerated movement
- Keep animation duration under 500ms for interactive feedback
- Use ease-out for natural feel
- Limit concurrent animations to avoid main-thread blocking

## Component Library Summary

| Component | Category | Status |
|---|---|---|
| PillNav | Navigation | ✅ Existing (base.html) — restyle needed |
| Hero | Homepage | ✅ Template exists — redesign needed |
| Ticker | Global | ✅ Template exists — restyle needed |
| SearchBar | Discovery | ✅ Template exists — enhance |
| OppCard | Opportunity | ✅ Template exists (_items.html) — restyle needed |
| FilterChip | Filtering | ✅ Template exists (list.html) — enhance |
| DetailCard | Detail | ✅ Template exists (detail.html) — restyle needed |
| Dashboard | Student | ❌ Needs building |
| AppTracker | Applications | ✅ Template exists (applications.html) — enhance |
| AgentCard | Monitoring | ❌ Needs building (16 agents) |
| AdminDashboard | Admin | ❌ Needs building |
| TrustBadge | Verification | ✅ Can reuse existing tag system |
| ProfileForm | Profile | ✅ Template exists (profile.html) — enhance |
| MovingTicker | Global | ✅ Template exists (index.html) — restyle needed |

## Moving to Production

1. **Design system first** — establish CSS tokens, color palette, typography scale
2. **Component-by-component** — build each page using real backend data
3. **API integration** — connect frontend to Flask routes + FastAPI JSON endpoints
4. **Responsive testing** — test at all breakpoints (1400, 1080, 760, 460)
5. **Accessibility audit** — keyboard nav, contrast, screen reader
6. **Error state verification** — every component has loading/empty/error/success
7. **SEO audit** — meta tags, open graph, sitemap, canonical URLs
8. **Performance audit** — lazy loading, bundle size, render time
9. **Cross-browser testing** — Chrome, Firefox, Safari
10. **User testing** — validate flows with real users