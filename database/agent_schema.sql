-- AAWARA Agent System tables

CREATE TABLE IF NOT EXISTS agent_tasks (
    id              INTEGER PRIMARY KEY,
    task_id         TEXT UNIQUE NOT NULL,
    agent_id        TEXT NOT NULL,
    job_type        TEXT,
    priority        TEXT DEFAULT 'medium',
    status          TEXT DEFAULT 'QUEUED',
    input_data      TEXT,
    output_data     TEXT,
    confidence      REAL,
    error           TEXT,
    retry_count     INTEGER DEFAULT 0,
    created_at      TEXT,
    started_at      TEXT,
    completed_at    TEXT,
    duration_ms     INTEGER,
    parent_task_id  TEXT,
    source_id       INTEGER,
    opportunity_id  INTEGER
);

CREATE INDEX IF NOT EXISTS idx_agent_tasks_agent_id ON agent_tasks(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_status ON agent_tasks(status);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_created_at ON agent_tasks(created_at);

CREATE TABLE IF NOT EXISTS agent_events (
    id              INTEGER PRIMARY KEY,
    event_type      TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    data            TEXT,
    created_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_events_type ON agent_events(event_type);
CREATE INDEX IF NOT EXISTS idx_agent_events_agent ON agent_events(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_events_created ON agent_events(created_at);

CREATE TABLE IF NOT EXISTS agent_metrics (
    id              INTEGER PRIMARY KEY,
    agent_id        TEXT NOT NULL,
    metric_name     TEXT NOT NULL,
    metric_value    REAL,
    recorded_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_metrics_agent ON agent_metrics(agent_id);

CREATE TABLE IF NOT EXISTS opportunity_evidence (
    id              INTEGER PRIMARY KEY,
    opportunity_id  INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    field           TEXT NOT NULL,
    value           TEXT,
    source_url      TEXT,
    source_text     TEXT,
    confidence      REAL,
    agent_id        TEXT,
    created_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_evidence_opportunity ON opportunity_evidence(opportunity_id);
CREATE INDEX IF NOT EXISTS idx_evidence_field ON opportunity_evidence(field);

CREATE TABLE IF NOT EXISTS opportunity_changes (
    id              INTEGER PRIMARY KEY,
    opportunity_id  INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    change_type     TEXT NOT NULL,
    old_value       TEXT,
    new_value       TEXT,
    detected_at     TEXT,
    notified        INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_changes_opportunity ON opportunity_changes(opportunity_id);
