-- Opportunity Bot — SQLite schema (Phase 3)
-- Portable SQL: designed so the connection layer can be swapped to PostgreSQL later.

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY,
    username        TEXT UNIQUE,
    password_hash   TEXT,
    google_id       TEXT,
    github_id       TEXT,
    email           TEXT,
    chat_id         TEXT,
    telegram_username TEXT,
    role            TEXT NOT NULL DEFAULT 'user',
    country         TEXT,
    citizenship     TEXT,
    degree          TEXT,
    degree_level    TEXT,
    current_year    INTEGER,
    cgpa            REAL,
    resume_json     TEXT,
    api_token_hash  TEXT,
    university      TEXT,
    branch          TEXT,
    graduation_year INTEGER,
    skills_json     TEXT,
    interests_json  TEXT,
    eligible_years_json TEXT,
    preferred_json  TEXT,
    allow_json      TEXT,
    created_at      TEXT,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token       TEXT UNIQUE NOT NULL,
    token_algo  TEXT,
    created_at  TEXT,
    expires_at  TEXT
);

CREATE TABLE IF NOT EXISTS bookmarks (
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    opportunity_id  INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    created_at      TEXT,
    PRIMARY KEY (user_id, opportunity_id)
);

CREATE TABLE IF NOT EXISTS applications (
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    opportunity_id  INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'applied',
    applied_at      TEXT,
    updated_at      TEXT,
    notes           TEXT,
    PRIMARY KEY (user_id, opportunity_id)
);

CREATE TABLE IF NOT EXISTS opportunities (
    id                      INTEGER PRIMARY KEY,
    dedup_key               TEXT UNIQUE,
    title                   TEXT NOT NULL,
    organization            TEXT,
    type                    TEXT,
    category                TEXT,
    description             TEXT,
    location                TEXT,
    country                 TEXT,
    remote                  INTEGER DEFAULT 0,
    hybrid                  INTEGER DEFAULT 0,
    deadline                TEXT,
    listed_at               TEXT,
    start_date              TEXT,
    end_date                TEXT,
    duration                TEXT,
    eligible_countries_json TEXT,
    eligible_degrees_json   TEXT,
    eligible_years_json     TEXT,
    eligible_branches_json  TEXT,
    minimum_gpa             TEXT,
    requirements_json       TEXT,
    preferred_skills_json   TEXT,
    stipend                 TEXT,
    currency                TEXT,
    funding                 TEXT,
    travel_support          TEXT,
    housing_support         TEXT,
    application_url         TEXT,
    official_url            TEXT,
    source_url              TEXT,
    source_type             TEXT,
    organization_trust_score INTEGER,
    verification_status     TEXT,
    eligibility_status      TEXT,
    match_score             REAL,
    first_seen              TEXT,
    last_seen               TEXT,
    status                  TEXT DEFAULT 'new',
    saved                   INTEGER DEFAULT 0,
    duplicate_of            INTEGER REFERENCES opportunities(id)
);

CREATE INDEX IF NOT EXISTS idx_opportunities_status ON opportunities(status);
CREATE INDEX IF NOT EXISTS idx_opportunities_deadline ON opportunities(deadline);
CREATE INDEX IF NOT EXISTS idx_opportunities_match_score ON opportunities(match_score);

CREATE TABLE IF NOT EXISTS sources (
    id                  INTEGER PRIMARY KEY,
    name                TEXT NOT NULL,
    organization        TEXT,
    type                TEXT,
    category            TEXT,
    url                 TEXT UNIQUE NOT NULL,
    method              TEXT,
    priority            INTEGER DEFAULT 0,
    trust_score         INTEGER DEFAULT 50,
    enabled             INTEGER DEFAULT 1,
    last_checked        TEXT,
    check_frequency_hours INTEGER DEFAULT 6,
    include_patterns    TEXT,
    exclude_patterns    TEXT,
    max_pages           INTEGER DEFAULT 10,
    result_limit        INTEGER DEFAULT 100,
    rate_limit_ms       INTEGER DEFAULT 1500,
    location_filter     TEXT DEFAULT 'india_remote',
    role_patterns_json  TEXT,
    last_success        TEXT,
    last_failure        TEXT,
    consecutive_failures INTEGER DEFAULT 0,
    cooldown_until      TEXT
);

CREATE TABLE IF NOT EXISTS opportunity_sources (
    opportunity_id  INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    source_id       INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    seen_at         TEXT,
    PRIMARY KEY (opportunity_id, source_id)
);

CREATE TABLE IF NOT EXISTS eligibility_results (
    id                      INTEGER PRIMARY KEY,
    opportunity_id          INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    user_id                 INTEGER REFERENCES users(id),
    status                  TEXT,
    reasons_json            TEXT,
    missing_information_json TEXT,
    checked_at              TEXT
);

CREATE TABLE IF NOT EXISTS scores (
    id              INTEGER PRIMARY KEY,
    opportunity_id  INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    user_id         INTEGER REFERENCES users(id),
    score           REAL,
    components_json TEXT,
    computed_at     TEXT
);

CREATE TABLE IF NOT EXISTS notifications (
    id              INTEGER PRIMARY KEY,
    opportunity_id  INTEGER REFERENCES opportunities(id) ON DELETE CASCADE,
    user_id         INTEGER REFERENCES users(id),
    channel         TEXT DEFAULT 'telegram',
    kind            TEXT,
    message         TEXT,
    sent_at         TEXT,
    delivered       INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS deadlines (
    id              INTEGER PRIMARY KEY,
    opportunity_id  INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    deadline        TEXT,
    notified_30d    INTEGER DEFAULT 0,
    notified_14d    INTEGER DEFAULT 0,
    notified_7d     INTEGER DEFAULT 0,
    notified_3d     INTEGER DEFAULT 0,
    notified_24h    INTEGER DEFAULT 0,
    expired         INTEGER DEFAULT 0,
    updated_at      TEXT,
    UNIQUE (opportunity_id)
);

CREATE TABLE IF NOT EXISTS execution_logs (
    id          INTEGER PRIMARY KEY,
    run_id      TEXT,
    workflow    TEXT,
    step        TEXT,
    status      TEXT,
    message     TEXT,
    started_at  TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS duplicates (
    id              INTEGER PRIMARY KEY,
    opportunity_id  INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    duplicate_of_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    similarity      REAL NOT NULL,
    method          TEXT NOT NULL,
    detected_at     TEXT
);

CREATE TABLE IF NOT EXISTS verifications (
    id              INTEGER PRIMARY KEY,
    opportunity_id  INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    status          TEXT NOT NULL,
    link_status     TEXT,
    message         TEXT,
    checked_at      TEXT
);

CREATE TABLE IF NOT EXISTS search_queries (
    id            INTEGER PRIMARY KEY,
    query         TEXT,
    engine        TEXT,
    ran_at        TEXT,
    result_count  INTEGER
);

CREATE TABLE IF NOT EXISTS system_errors (
    id          INTEGER PRIMARY KEY,
    component   TEXT,
    error_type  TEXT,
    message     TEXT,
    traceback   TEXT,
    occurred_at TEXT,
    resolved    INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ai_assessments (
    id              INTEGER PRIMARY KEY,
    opportunity_id  INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    verdict         TEXT,
    reason          TEXT,
    deadline_guess  TEXT,
    confidence      REAL,
    model           TEXT,
    created_at      TEXT
);

CREATE TABLE IF NOT EXISTS discovery_runs (
    id              INTEGER PRIMARY KEY,
    run_id          TEXT,
    scout           TEXT,
    source_id       INTEGER,
    source_name     TEXT,
    source_url      TEXT,
    method          TEXT,
    crawler         TEXT,
    raw_items       INTEGER DEFAULT 0,
    role_gate       INTEGER DEFAULT 0,
    location_gate   INTEGER DEFAULT 0,
    pattern_gate    INTEGER DEFAULT 0,
    extracted       INTEGER DEFAULT 0,
    stored_new      INTEGER DEFAULT 0,
    duplicates      INTEGER DEFAULT 0,
    eligible        INTEGER DEFAULT 0,
    likely_eligible INTEGER DEFAULT 0,
    unclear         INTEGER DEFAULT 0,
    not_eligible    INTEGER DEFAULT 0,
    published       INTEGER DEFAULT 0,
    extraction_errors INTEGER DEFAULT 0,
    retries         INTEGER DEFAULT 0,
    http_status     INTEGER,
    response_ms     INTEGER,
    error           TEXT,
    started_at      TEXT,
finished_at      TEXT
);

CREATE TABLE IF NOT EXISTS crawl_jobs (
    id              INTEGER PRIMARY KEY,
    run_id          TEXT,
    source_id       INTEGER,
    source_name     TEXT,
    url             TEXT,
    crawler         TEXT,
    priority        TEXT,
    status          TEXT DEFAULT 'QUEUED',
    retry_count     INTEGER DEFAULT 0,
    items_found     INTEGER DEFAULT 0,
    items_created   INTEGER DEFAULT 0,
    items_updated   INTEGER DEFAULT 0,
    duplicates_found INTEGER DEFAULT 0,
    error           TEXT,
    started_at      TEXT,
    completed_at    TEXT
);

CREATE TABLE IF NOT EXISTS reports (
    id              INTEGER PRIMARY KEY,
    opportunity_id  INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    reporter_id     INTEGER,
    reason          TEXT,
    notes           TEXT,
    status          TEXT DEFAULT 'pending',
    created_at      TEXT,
    resolved_at     TEXT
);

CREATE TABLE IF NOT EXISTS source_health (
    id                  INTEGER PRIMARY KEY,
    source_id           INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    ok                  INTEGER NOT NULL,
    status_code         INTEGER,
    message             TEXT,
    response_ms         INTEGER,
    consecutive_failures INTEGER DEFAULT 0,
    cooldown_until      TEXT,
    checked_at          TEXT
);

CREATE TABLE IF NOT EXISTS filtering_decisions (
    id              INTEGER PRIMARY KEY,
    run_id          TEXT,
    source_id       INTEGER,
    stage           TEXT,
    title           TEXT,
    organization    TEXT,
    url             TEXT,
    reason          TEXT,
    decided_at      TEXT
);

CREATE TABLE IF NOT EXISTS raw_responses (
    id          INTEGER PRIMARY KEY,
    run_id      TEXT,
    source_id   INTEGER,
    source_name TEXT,
    url         TEXT,
    status      INTEGER,
    bytes       INTEGER,
    sha256      TEXT,
    saved_path  TEXT,
    stored_at   TEXT
);