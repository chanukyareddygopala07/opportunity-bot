"""Phase 3 — SQLite database layer. Portable SQL, thin connection, JSON columns.

Swap get_connection() for a PostgreSQL driver later; the rest stays.
"""
import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src import schema
from src import deadlines as _deadlines
from src import trust as _trust

BASE_DIR = Path(__file__).resolve().parent.parent
SCHEMA_FILE = BASE_DIR / "database" / "schema.sql"
DEFAULT_DB = BASE_DIR / "data" / "opportunity.db"

OPP_JSON_COLUMNS = (
    "eligible_countries", "eligible_degrees", "eligible_years",
    "eligible_branches", "requirements", "preferred_skills",
)

OPP_BOOL_COLUMNS = ("remote", "hybrid", "saved")

# Default-argument sentinel (distinguishes "not provided" from None).
_SENTINEL = object()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_database_path():
    return os.environ.get("DATABASE_PATH", str(DEFAULT_DB))


def get_connection():
    path = get_database_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # Concurrency hardening: WAL lets readers work during writes and
    # busy_timeout makes multi-container access retry instead of erroring
    # with "database is locked" on first contention.
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db():
    conn = get_connection()
    try:
        conn.executescript(SCHEMA_FILE.read_text())
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()


def _migrate(conn):
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(sources)")}
    for column, ddl in (
        ("include_patterns", "TEXT"),
        ("exclude_patterns", "TEXT"),
        ("max_pages", "INTEGER DEFAULT 10"),
        ("result_limit", "INTEGER DEFAULT 100"),
        ("rate_limit_ms", "INTEGER DEFAULT 1500"),
        ("location_filter", "TEXT DEFAULT 'india_remote'"),
        ("role_patterns_json", "TEXT"),
        ("last_success", "TEXT"),
        ("last_failure", "TEXT"),
        ("consecutive_failures", "INTEGER DEFAULT 0"),
        ("cooldown_until", "TEXT"),
        ("adapter", "TEXT"),
    ):
        if column not in existing:
            conn.execute(f"ALTER TABLE sources ADD COLUMN {column} {ddl}")
    opp_columns = {row["name"] for row in conn.execute("PRAGMA table_info(opportunities)")}
    if "listed_at" not in opp_columns:
        conn.execute("ALTER TABLE opportunities ADD COLUMN listed_at TEXT")
    if "duplicate_of" not in opp_columns:
        conn.execute(
            "ALTER TABLE opportunities ADD COLUMN duplicate_of INTEGER "
            "REFERENCES opportunities(id)"
        )
    for column, ddl in (
        ("deadline_status", "TEXT"),
        ("trust_score", "INTEGER"),
        ("next_verification", "TEXT"),
    ):
        if column not in opp_columns:
            conn.execute(f"ALTER TABLE opportunities ADD COLUMN {column} {ddl}")
    for index, ddl in (
        ("idx_opp_deadline_status",
         "CREATE INDEX IF NOT EXISTS idx_opp_deadline_status "
         "ON opportunities(deadline_status)"),
        ("idx_opp_trust_score",
         "CREATE INDEX IF NOT EXISTS idx_opp_trust_score "
         "ON opportunities(trust_score)"),
        ("idx_opp_type",
         "CREATE INDEX IF NOT EXISTS idx_opp_type ON opportunities(type)"),
        ("idx_opp_last_seen",
         "CREATE INDEX IF NOT EXISTS idx_opp_last_seen "
         "ON opportunities(last_seen)"),
        ("idx_crawl_jobs_status",
         "CREATE INDEX IF NOT EXISTS idx_crawl_jobs_status "
         "ON crawl_jobs(status)"),
        ("idx_discovery_runs_run_id",
         "CREATE INDEX IF NOT EXISTS idx_discovery_runs_run_id "
         "ON discovery_runs(run_id)"),
    ):
        if index not in {
            row["name"] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }:
            conn.execute(ddl)
    run_columns = {row["name"] for row in conn.execute("PRAGMA table_info(discovery_runs)")}
    if "crawler" not in run_columns:
        conn.execute("ALTER TABLE discovery_runs ADD COLUMN crawler TEXT")
    session_columns = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
    if "token_algo" not in session_columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN token_algo TEXT")
    user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    for column, ddl in (
        ("citizenship", "TEXT"),
        ("degree_level", "TEXT"),
        ("eligible_years_json", "TEXT"),
        ("username", "TEXT"),
        ("password_hash", "TEXT"),
        ("google_id", "TEXT"),
        ("github_id", "TEXT"),
        ("email", "TEXT"),
        ("cgpa", "REAL"),
        ("resume_json", "TEXT"),
        ("api_token_hash", "TEXT"),
        ("role", "TEXT NOT NULL DEFAULT 'user'"),
    ):
        if column not in user_columns:
            conn.execute(f"ALTER TABLE users ADD COLUMN {column} {ddl}")
    if "username" in user_columns:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username)"
        )
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS opportunities_fts USING fts5("
        "title, organization, description, location, country, "
        "content='opportunities', content_rowid='id')"
    )
    triggers = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        )
    }
    fts_rebuilt = False
    if "opportunities_ai" not in triggers:
        conn.execute(
            "CREATE TRIGGER opportunities_ai AFTER INSERT ON opportunities BEGIN "
            "INSERT INTO opportunities_fts(rowid, title, organization, description, location, country) "
            "VALUES (new.id, new.title, new.organization, new.description, new.location, new.country); END"
        )
        fts_rebuilt = True
    if "opportunities_ad" not in triggers:
        conn.execute(
            "CREATE TRIGGER opportunities_ad AFTER DELETE ON opportunities BEGIN "
            "INSERT INTO opportunities_fts(opportunities_fts, rowid, title, organization, description, location, country) "
            "VALUES ('delete', old.id, old.title, old.organization, old.description, old.location, old.country); END"
        )
        fts_rebuilt = True
    if "opportunities_au" not in triggers:
        conn.execute(
            "CREATE TRIGGER opportunities_au AFTER UPDATE ON opportunities BEGIN "
            "INSERT INTO opportunities_fts(opportunities_fts, rowid, title, organization, description, location, country) "
            "VALUES ('delete', old.id, old.title, old.organization, old.description, old.location, old.country); "
            "INSERT INTO opportunities_fts(rowid, title, organization, description, location, country) "
            "VALUES (new.id, new.title, new.organization, new.description, new.location, new.country); END"
        )
        fts_rebuilt = True
    if fts_rebuilt:
        # Rebuilding on every init costs O(table); only do it when the FTS
        # wiring itself changed.
        conn.execute("INSERT INTO opportunities_fts(opportunities_fts) VALUES('rebuild')")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_github_id ON users(github_id)"
    )
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    for name, ddl in (
        ("discovery_runs", (
            "CREATE TABLE IF NOT EXISTS discovery_runs ("
            "id INTEGER PRIMARY KEY, run_id TEXT, scout TEXT, source_id INTEGER, "
            "source_name TEXT, source_url TEXT, method TEXT, crawler TEXT, "
            "raw_items INTEGER DEFAULT 0, role_gate INTEGER DEFAULT 0, "
            "location_gate INTEGER DEFAULT 0, pattern_gate INTEGER DEFAULT 0, "
            "extracted INTEGER DEFAULT 0, stored_new INTEGER DEFAULT 0, "
            "duplicates INTEGER DEFAULT 0, eligible INTEGER DEFAULT 0, "
            "likely_eligible INTEGER DEFAULT 0, unclear INTEGER DEFAULT 0, "
            "not_eligible INTEGER DEFAULT 0, published INTEGER DEFAULT 0, "
            "extraction_errors INTEGER DEFAULT 0, retries INTEGER DEFAULT 0, "
            "http_status INTEGER, response_ms INTEGER, error TEXT, "
            "started_at TEXT, finished_at TEXT)"
        )),
        ("crawl_jobs", (
            "CREATE TABLE IF NOT EXISTS crawl_jobs ("
            "id INTEGER PRIMARY KEY, run_id TEXT, source_id INTEGER, "
            "source_name TEXT, url TEXT, crawler TEXT, priority TEXT, "
            "status TEXT DEFAULT 'QUEUED', retry_count INTEGER DEFAULT 0, "
            "items_found INTEGER DEFAULT 0, items_created INTEGER DEFAULT 0, "
            "items_updated INTEGER DEFAULT 0, duplicates_found INTEGER DEFAULT 0, "
            "error TEXT, started_at TEXT, completed_at TEXT)"
        )),
        ("reports", (
            "CREATE TABLE IF NOT EXISTS reports ("
            "id INTEGER PRIMARY KEY, opportunity_id INTEGER NOT NULL "
            "REFERENCES opportunities(id) ON DELETE CASCADE, reporter_id INTEGER, "
            "reason TEXT, notes TEXT, status TEXT DEFAULT 'pending', "
            "created_at TEXT, resolved_at TEXT)"
        )),
        ("source_health", (
            "CREATE TABLE IF NOT EXISTS source_health ("
            "id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sources(id) "
            "ON DELETE CASCADE, ok INTEGER NOT NULL, status_code INTEGER, "
            "message TEXT, response_ms INTEGER, consecutive_failures INTEGER DEFAULT 0, "
            "cooldown_until TEXT, checked_at TEXT)"
        )),
        ("filtering_decisions", (
            "CREATE TABLE IF NOT EXISTS filtering_decisions ("
            "id INTEGER PRIMARY KEY, run_id TEXT, source_id INTEGER, stage TEXT, "
            "title TEXT, organization TEXT, url TEXT, reason TEXT, decided_at TEXT)"
        )),
        ("raw_responses", (
            "CREATE TABLE IF NOT EXISTS raw_responses ("
            "id INTEGER PRIMARY KEY, run_id TEXT, source_id INTEGER, source_name TEXT, "
            "url TEXT, status INTEGER, bytes INTEGER, sha256 TEXT, saved_path TEXT, "
            "stored_at TEXT)"
        )),
        ("chat_messages", (
            "CREATE TABLE IF NOT EXISTS chat_messages ("
            "id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) "
            "ON DELETE CASCADE, role TEXT NOT NULL, content TEXT NOT NULL, "
            "provider TEXT, conversation_id TEXT, feedback TEXT, created_at TEXT)"
        )),
        ("user_views", (
            "CREATE TABLE IF NOT EXISTS user_views ("
            "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
            "opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) "
            "ON DELETE CASCADE, viewed_at TEXT, PRIMARY KEY (user_id, opportunity_id))"
        )),
    ):
        if name not in tables:
            conn.execute(ddl)
    if "sessions" not in tables:
        conn.execute(
            "CREATE TABLE sessions ("
            "id INTEGER PRIMARY KEY, "
            "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
            "token TEXT UNIQUE NOT NULL, "
            "created_at TEXT, "
            "expires_at TEXT)"
        )
    if "bookmarks" not in tables:
        conn.execute(
            "CREATE TABLE bookmarks ("
            "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
            "opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) "
            "ON DELETE CASCADE, "
            "created_at TEXT, "
            "PRIMARY KEY (user_id, opportunity_id))"
        )
    if "applications" not in tables:
        conn.execute(
            "CREATE TABLE applications ("
            "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
            "opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) "
            "ON DELETE CASCADE, "
            "status TEXT NOT NULL DEFAULT 'applied', "
            "applied_at TEXT, "
            "updated_at TEXT, "
            "notes TEXT, "
            "PRIMARY KEY (user_id, opportunity_id))"
        )
    if "duplicates" not in tables:
        conn.execute(
            "CREATE TABLE duplicates ("
            "id INTEGER PRIMARY KEY, "
            "opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE, "
            "duplicate_of_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE, "
            "similarity REAL NOT NULL, "
            "method TEXT NOT NULL, "
            "detected_at TEXT)"
        )
    if "verifications" not in tables:
        conn.execute(
            "CREATE TABLE verifications ("
            "id INTEGER PRIMARY KEY, "
            "opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE, "
            "status TEXT NOT NULL, "
            "link_status TEXT, "
            "message TEXT, "
            "checked_at TEXT)"
        )
    if "ai_assessments" not in tables:
        conn.execute(
            "CREATE TABLE ai_assessments ("
            "id INTEGER PRIMARY KEY, "
            "opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE, "
            "verdict TEXT, "
            "reason TEXT, "
            "deadline_guess TEXT, "
            "confidence REAL, "
            "model TEXT, "
            "created_at TEXT)"
        )
    # --- AAWARA Agent System tables ---
    agent_tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    if "agent_tasks" not in agent_tables:
        conn.execute(
            "CREATE TABLE agent_tasks ("
            "id INTEGER PRIMARY KEY, "
            "task_id TEXT UNIQUE NOT NULL, "
            "agent_id TEXT NOT NULL, "
            "job_type TEXT, "
            "priority TEXT DEFAULT 'medium', "
            "status TEXT DEFAULT 'QUEUED', "
            "input_data TEXT, "
            "output_data TEXT, "
            "confidence REAL, "
            "error TEXT, "
            "retry_count INTEGER DEFAULT 0, "
            "created_at TEXT, "
            "started_at TEXT, "
            "completed_at TEXT, "
            "duration_ms INTEGER, "
            "parent_task_id TEXT, "
            "source_id INTEGER, "
            "opportunity_id INTEGER)"
        )
    if "agent_events" not in agent_tables:
        conn.execute(
            "CREATE TABLE agent_events ("
            "id INTEGER PRIMARY KEY, "
            "event_id TEXT UNIQUE, "
            "event_type TEXT NOT NULL, "
            "agent_id TEXT NOT NULL, "
            "data TEXT, "
            "created_at TEXT)"
        )
    event_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(agent_events)")
    } if "agent_events" in agent_tables else set()
    if "event_id" not in event_columns and "agent_events" in agent_tables:
        conn.execute("ALTER TABLE agent_events ADD COLUMN event_id TEXT")
    if "agent_metrics" not in agent_tables:
        conn.execute(
            "CREATE TABLE agent_metrics ("
            "id INTEGER PRIMARY KEY, "
            "agent_id TEXT NOT NULL, "
            "metric_name TEXT NOT NULL, "
            "metric_value REAL, "
            "recorded_at TEXT)"
        )
    if "opportunity_evidence" not in agent_tables:
        conn.execute(
            "CREATE TABLE opportunity_evidence ("
            "id INTEGER PRIMARY KEY, "
            "opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE, "
            "field TEXT NOT NULL, "
            "value TEXT, "
            "source_url TEXT, "
            "source_text TEXT, "
            "confidence REAL, "
            "agent_id TEXT, "
            "created_at TEXT)"
        )
    if "opportunity_changes" not in agent_tables:
        conn.execute(
            "CREATE TABLE opportunity_changes ("
            "id INTEGER PRIMARY KEY, "
            "opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE, "
            "change_type TEXT NOT NULL, "
            "old_value TEXT, "
            "new_value TEXT, "
            "detected_at TEXT, "
            "notified INTEGER DEFAULT 0)"
        )
    # Agent indexes
    agent_indexes = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
    }
    for index, ddl in (
        ("idx_agent_tasks_agent_id",
         "CREATE INDEX IF NOT EXISTS idx_agent_tasks_agent_id ON agent_tasks(agent_id)"),
        ("idx_agent_tasks_status",
         "CREATE INDEX IF NOT EXISTS idx_agent_tasks_status ON agent_tasks(status)"),
        ("idx_agent_events_type",
         "CREATE INDEX IF NOT EXISTS idx_agent_events_type ON agent_events(event_type)"),
        ("idx_agent_events_agent",
         "CREATE INDEX IF NOT EXISTS idx_agent_events_agent ON agent_events(agent_id)"),
        ("idx_evidence_opportunity",
         "CREATE INDEX IF NOT EXISTS idx_evidence_opportunity ON opportunity_evidence(opportunity_id)"),
        ("idx_changes_opportunity",
         "CREATE INDEX IF NOT EXISTS idx_changes_opportunity ON opportunity_changes(opportunity_id)"),
    ):
        if index not in agent_indexes:
            conn.execute(ddl)
    # Legacy chat_messages upgrades (Rudra conversations + feedback) — must
    # run after every table-creation step above on fresh databases.
    final_tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    if "chat_messages" in final_tables:
        chat_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(chat_messages)")
        }
        if "conversation_id" not in chat_columns:
            conn.execute("ALTER TABLE chat_messages ADD COLUMN conversation_id TEXT")
        if "feedback" not in chat_columns:
            conn.execute("ALTER TABLE chat_messages ADD COLUMN feedback TEXT")


def _dumps(value):
    return json.dumps(value, ensure_ascii=False) if value is not None else None


def _loads(value):
    return json.loads(value) if value else None


def row_to_opportunity(row):
    opp = dict(row)
    for key in OPP_JSON_COLUMNS:
        opp[key] = _loads(opp.get(key + "_json"))
    for key in OPP_BOOL_COLUMNS:
        opp[key] = bool(opp.get(key))
    return opp


def make_dedup_key(title, organization, application_url, deadline):
    parts = [
        str(title or "").strip().lower(),
        str(organization or "").strip().lower(),
        str(application_url or "").strip().lower(),
        str(deadline or "").strip().lower(),
    ]
    return "|".join(parts)


# --- opportunities ---

# Fields whose changes are historically tracked (change detection).
TRACKED_CHANGE_FIELDS = (
    "deadline", "application_url", "official_url", "eligibility_status",
    "stipend", "funding", "title", "status", "start_date", "end_date",
)


def _diff_opportunity(old_row, new_opp):
    """Field-level diff between stored row and incoming normalized data.

    Returns a list of (field, old_value, new_value) tuples for tracked fields
    where the value actually changed. Never treats missing-as-change.
    """
    changes = []
    for field in TRACKED_CHANGE_FIELDS:
        old_value = old_row.get(field)
        new_value = new_opp.get(field)
        if (old_value or None) == (new_value or None):
            continue
        if old_value is None and not new_value:
            continue
        changes.append((field, old_value, new_value))
    return changes


def upsert_opportunity(opp):
    opp = schema.normalize_opportunity(opp)
    opp["dedup_key"] = make_dedup_key(
        opp.get("title"), opp.get("organization"),
        opp.get("application_url"), opp.get("deadline"),
    )
    for key in OPP_JSON_COLUMNS:
        opp[key + "_json"] = _dumps(opp.get(key))
    for key in OPP_BOOL_COLUMNS:
        opp[key] = 1 if opp.get(key) else 0
    if not opp.get("title"):
        raise ValueError("opportunity title is required")
    errors, _warnings = schema.validate_opportunity(opp)
    if errors:
        raise ValueError(f"invalid opportunity: {'; '.join(errors)}")
    ts = now_iso()
    opp["first_seen"] = opp.get("first_seen") or ts
    opp["last_seen"] = ts
    opp["deadline_status"] = _deadlines.status(opp)
    opp["trust_score"] = _trust.compute(opp)[0]
    columns = [
        "dedup_key", "title", "organization", "type", "category", "description",
        "location", "country", "remote", "hybrid", "deadline", "listed_at", "start_date",
        "end_date", "duration", "eligible_countries_json", "eligible_degrees_json",
        "eligible_years_json", "eligible_branches_json", "minimum_gpa",
        "requirements_json", "preferred_skills_json", "stipend", "currency",
        "funding", "travel_support", "housing_support", "application_url",
        "official_url", "source_url", "source_type", "organization_trust_score",
        "verification_status", "eligibility_status", "match_score",
        "first_seen", "last_seen", "status", "saved",
        "deadline_status", "trust_score",
    ]
    placeholders = ", ".join("?" for _ in columns)
    updates = ", ".join(f"{c} = excluded.{c}" for c in columns if c != "dedup_key")
    sql = (
        f"INSERT INTO opportunities ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT (dedup_key) DO UPDATE SET {updates}"
    )
    values = [opp.get(c) for c in columns]
    conn = get_connection()
    try:
        # Change detection: read prior state before the write lands.
        existing = conn.execute(
            "SELECT * FROM opportunities WHERE dedup_key = ?",
            (opp["dedup_key"],),
        ).fetchone()
        cursor = conn.execute(sql, values)
        conn.commit()
        opportunity_id = cursor.lastrowid
        if not opportunity_id:
            row = conn.execute(
                "SELECT id FROM opportunities WHERE dedup_key = ?",
                (opp["dedup_key"],),
            ).fetchone()
            opportunity_id = row["id"] if row else None
        if existing and opportunity_id:
            try:
                for field, old_value, new_value in _diff_opportunity(
                        dict(existing), opp):
                    record_opportunity_change(
                        opportunity_id,
                        f"{field}_changed",
                        str(old_value) if old_value is not None else None,
                        str(new_value) if new_value is not None else None,
                    )
            except Exception as exc:  # change log must never block ingestion
                import logging
                logging.getLogger(__name__).warning(
                    "change recording failed: %s", exc)
        return opportunity_id
    finally:
        conn.close()


def fts_search_ids(query, limit=100):
    """Ranked full-text search over title/org/description/location/country.

    Returns a list of opportunity ids, or None when FTS is unavailable so
    callers can fall back to substring matching.
    """
    words = [w.lower() for w in re.findall(r"[\w\-]+", query or "") if len(w) >= 2]
    if not words:
        return None
    match = " AND ".join('"%s"' % w.replace('"', '""') for w in words[:8])
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT rowid FROM opportunities_fts "
            "WHERE opportunities_fts MATCH ? ORDER BY rank LIMIT ?",
            (match, int(limit)),
        ).fetchall()
        return [r["rowid"] for r in rows]
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return None
    finally:
        conn.close()


def list_opportunities(limit=None, status=None, opp_type=None, exclude_duplicates=True):
    sql = "SELECT * FROM opportunities"
    where = []
    params = []
    if status:
        where.append("status = ?")
        params.append(status)
    if opp_type:
        where.append("(type LIKE ? OR category LIKE ? OR title LIKE ?)")
        params += [f"%{opp_type}%"] * 3
    if exclude_duplicates:
        where.append("duplicate_of IS NULL")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY match_score DESC NULLS LAST, last_seen DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    conn = get_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [row_to_opportunity(r) for r in rows]
    finally:
        conn.close()


def get_opportunity(opportunity_id):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM opportunities WHERE id = ?", (opportunity_id,)).fetchone()
        return row_to_opportunity(row) if row else None
    finally:
        conn.close()


def toggle_saved(opportunity_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT saved FROM opportunities WHERE id = ?", (opportunity_id,)
        ).fetchone()
        if not row:
            return None
        new_value = 0 if row["saved"] else 1
        conn.execute(
            "UPDATE opportunities SET saved = ? WHERE id = ?", (new_value, opportunity_id)
        )
        conn.commit()
        return bool(new_value)
    finally:
        conn.close()


def update_opportunity(opportunity_id, **fields):
    allowed = {
        "eligibility_status", "match_score", "verification_status",
        "status", "saved", "last_seen", "deadline_status", "trust_score",
        "next_verification", "organization_trust_score",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    sql = "UPDATE opportunities SET " + ", ".join(f"{k} = ?" for k in updates) + " WHERE id = ?"
    conn = get_connection()
    try:
        conn.execute(sql, [*updates.values(), opportunity_id])
        conn.commit()
    finally:
        conn.close()


# --- users / profile ---

def upsert_user(profile, chat_id=None):
    profile = dict(profile)
    for key in ("skills", "interests", "preferred", "allow", "eligible_years"):
        profile[key] = _dumps(profile.get(key))
    ts = now_iso()
    columns = [
        "chat_id", "country", "citizenship", "degree", "degree_level",
        "current_year", "cgpa", "university", "branch", "graduation_year",
        "skills_json", "interests_json", "eligible_years_json",
        "preferred_json", "allow_json", "created_at", "updated_at",
    ]
    values = [
        chat_id, profile.get("country"), profile.get("citizenship"),
        profile.get("degree"), profile.get("degree_level"),
        profile.get("current_year"), profile.get("cgpa"),
        profile.get("university"),
        profile.get("branch"), profile.get("graduation_year"),
        profile.get("skills"), profile.get("interests"),
        profile.get("eligible_years"), profile.get("preferred"),
        profile.get("allow"), ts, ts,
    ]
    conn = get_connection()
    try:
        existing = conn.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
        if existing:
            updates = ", ".join(f"{c} = ?" for c in columns if c != "chat_id" or chat_id)
            params = [v for c, v in zip(columns, values) if c != "chat_id" or chat_id]
            sql = f"UPDATE users SET {updates}, updated_at = ? WHERE id = ?"
            conn.execute(sql, [*params, ts, existing["id"]])
            user_id = existing["id"]
        else:
            placeholders = ", ".join("?" for _ in columns)
            sql = f"INSERT INTO users ({', '.join(columns)}) VALUES ({placeholders})"
            cursor = conn.execute(sql, values)
            user_id = cursor.lastrowid
        conn.commit()
        return user_id
    finally:
        conn.close()


def set_user_chat_id(chat_id):
    conn = get_connection()
    try:
        conn.execute("UPDATE users SET chat_id = ?, updated_at = ? WHERE chat_id IS NULL", (str(chat_id), now_iso()))
        conn.commit()
    finally:
        conn.close()


def row_to_user(row):
    user = dict(row)
    for key in ("skills", "interests", "preferred", "allow", "eligible_years"):
        user[key] = _loads(user.get(key + "_json"))
    return user


def get_default_user():
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM users ORDER BY id LIMIT 1").fetchone()
        return row_to_user(row) if row else None
    finally:
        conn.close()


def get_user_by_chat(chat_id):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE chat_id = ?", (str(chat_id),)).fetchone()
        return row_to_user(row) if row else None
    finally:
        conn.close()


def get_user_by_id(user_id):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return row_to_user(row) if row else None
    finally:
        conn.close()


def get_user_by_username(username):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return row_to_user(row) if row else None
    finally:
        conn.close()


def set_user_role(user_id, role):
    if role not in ("user", "admin"):
        raise ValueError(f"invalid role: {role!r}")
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE users SET role = ?, updated_at = ? WHERE id = ?",
            (role, now_iso(), user_id),
        )
        conn.commit()
    finally:
        conn.close()


def bootstrap_admin(username):
    """Grant the admin role to the named existing user.

    Returns the affected user id, or None when the username is unset or no
    such user exists yet (the grant is retried on every startup until it
    succeeds — registration is the only way accounts are created).
    """
    if not username:
        return None
    user = get_user_by_username(username)
    if not user:
        return None
    if user.get("role") == "admin":
        return user["id"]
    set_user_role(user["id"], "admin")
    return user["id"]


def get_user_by_oauth(provider, provider_id):
    column = "google_id" if provider == "google" else "github_id"
    conn = get_connection()
    try:
        row = conn.execute(
            f"SELECT * FROM users WHERE {column} = ?", (str(provider_id),)
        ).fetchone()
        return row_to_user(row) if row else None
    finally:
        conn.close()


def get_user_by_email(email):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email or "",)
        ).fetchone()
        return row_to_user(row) if row else None
    finally:
        conn.close()


def link_oauth(user_id, provider, provider_id):
    column = "google_id" if provider == "google" else "github_id"
    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE users SET {column} = ?, updated_at = ? WHERE id = ?",
            (str(provider_id), now_iso(), user_id),
        )
        conn.commit()
    finally:
        conn.close()


def create_user(username, password_hash=None, profile=None, email=None,
               google_id=None, github_id=None):
    profile = profile or {}
    for key in ("skills", "interests", "preferred", "allow", "eligible_years"):
        profile[key] = _dumps(profile.get(key))
    ts = now_iso()
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, email, google_id, "
            "github_id, country, citizenship, degree, degree_level, "
            "current_year, university, branch, graduation_year, skills_json, "
            "interests_json, eligible_years_json, preferred_json, allow_json, "
            "created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                username, password_hash, email, google_id, github_id,
                profile.get("country"), profile.get("citizenship"),
                profile.get("degree"), profile.get("degree_level"),
                profile.get("current_year"), profile.get("university"),
                profile.get("branch"), profile.get("graduation_year"),
                profile.get("skills"), profile.get("interests"),
                profile.get("eligible_years"), profile.get("preferred"),
                profile.get("allow"), ts, ts,
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def update_user_fields(user_id, fields):
    conn = get_connection()
    try:
        sets, params = [], []
        for key, value in fields.items():
            column = key + "_json" if key in JSON_USER_FIELDS else key
            sets.append(f"{column} = ?")
            params.append(_dumps(value) if key in JSON_USER_FIELDS else value)
        if not sets:
            return False
        sets.append("updated_at = ?")
        params.append(now_iso())
        params.append(user_id)
        conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", params)
        conn.commit()
        return True
    finally:
        conn.close()


def _session_token_hash(token):
    """Sessions are stored hashed (SHA-256); a DB read must not yield a live token."""
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(user_id, token, expires_at):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO sessions (user_id, token, created_at, expires_at, token_algo) "
            "VALUES (?, ?, ?, ?, 'sha256')",
            (user_id, _session_token_hash(token), now_iso(), expires_at),
        )
        conn.commit()
    finally:
        conn.close()


def get_session(token):
    """Look up a session by its raw bearer token.

    Rows written since hashing was introduced store SHA-256(token). Rows from
    before the change store the raw token and are matched once, upgraded in
    place, and never re-stored plaintext. A leaked stored hash must NOT work
    as a credential, so legacy matching only applies to rows still marked as
    plaintext.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM sessions WHERE token = ?",
            (_session_token_hash(token),),
        ).fetchone()
        if not row:
            # One-time migration of legacy plaintext rows.
            legacy = conn.execute(
                "SELECT * FROM sessions WHERE token = ? "
                "AND (token_algo = 'plain' OR token_algo IS NULL)",
                (token,),
            ).fetchone()
            if not legacy:
                return None
            conn.execute(
                "UPDATE sessions SET token = ?, token_algo = 'sha256' WHERE id = ?",
                (_session_token_hash(token), legacy["id"]),
            )
            conn.commit()
            return dict(legacy)
        return dict(row)
    finally:
        conn.close()


def delete_session(token):
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM sessions WHERE token = ?", (_session_token_hash(token),)
        )
        # Legacy rows may still exist under their raw token.
        conn.execute(
            "DELETE FROM sessions WHERE token = ? "
            "AND (token_algo = 'plain' OR token_algo IS NULL)",
            (token,),
        )
        conn.commit()
    finally:
        conn.close()


def add_bookmark(user_id, opportunity_id):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO bookmarks (user_id, opportunity_id, created_at) "
            "VALUES (?, ?, ?)",
            (user_id, opportunity_id, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def remove_bookmark(user_id, opportunity_id):
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM bookmarks WHERE user_id = ? AND opportunity_id = ?",
            (user_id, opportunity_id),
        )
        conn.commit()
    finally:
        conn.close()


def is_bookmarked(user_id, opportunity_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM bookmarks WHERE user_id = ? AND opportunity_id = ?",
            (user_id, opportunity_id),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


# --- applications (Phase 8 tracking) ---

def upsert_application(user_id, opportunity_id, status="applied", notes=None):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO applications (user_id, opportunity_id, status, "
            "applied_at, updated_at, notes) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (user_id, opportunity_id) DO UPDATE SET "
            "status = excluded.status, updated_at = excluded.updated_at, "
            "notes = COALESCE(excluded.notes, applications.notes)",
            (user_id, opportunity_id, status, now_iso(), now_iso(), notes),
        )
        conn.commit()
    finally:
        conn.close()


def remove_application(user_id, opportunity_id):
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM applications WHERE user_id = ? AND opportunity_id = ?",
            (user_id, opportunity_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_application(user_id, opportunity_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM applications WHERE user_id = ? AND opportunity_id = ?",
            (user_id, opportunity_id),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_applications(user_id):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT a.*, o.title, o.organization, o.deadline, o.type, o.location "
            "FROM applications a JOIN opportunities o ON o.id = a.opportunity_id "
            "WHERE a.user_id = ? ORDER BY a.updated_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_bookmarks(user_id):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT o.* FROM bookmarks b JOIN opportunities o ON o.id = b.opportunity_id "
            "WHERE b.user_id = ? AND o.duplicate_of IS NULL "
            "ORDER BY b.created_at DESC",
            (user_id,),
        ).fetchall()
        return [row_to_opportunity(r) for r in rows]
    finally:
        conn.close()


JSON_USER_FIELDS = ("skills", "interests", "eligible_years")


def update_user_by_chat(chat_id, fields):
    conn = get_connection()
    try:
        user = conn.execute("SELECT id FROM users WHERE chat_id = ?", (str(chat_id),)).fetchone()
        if not user:
            return False
        sets, params = [], []
        for key, value in fields.items():
            column = key + "_json" if key in JSON_USER_FIELDS else key
            sets.append(f"{column} = ?")
            params.append(_dumps(value) if key in JSON_USER_FIELDS else value)
        if not sets:
            return True
        sets.append("updated_at = ?")
        params.append(now_iso())
        params.append(user["id"])
        conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", params)
        conn.commit()
        return True
    finally:
        conn.close()


# --- resume (Phase 19) ---

def get_user_resume(user_id):
    """Extra resume sections (education, experience, projects, awards,
    contact) stored on the user row as resume_json."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT resume_json FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return _loads(row["resume_json"]) if row and row["resume_json"] else {}
    finally:
        conn.close()


def save_user_resume(user_id, resume):
    """Replace the user's extra resume sections (fact-locked JSON)."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE users SET resume_json = ?, updated_at = ? WHERE id = ?",
            (_dumps(resume), now_iso(), user_id),
        )
        conn.commit()
    finally:
        conn.close()


def set_api_token_hash(user_id, token_hash):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE users SET api_token_hash = ?, updated_at = ? WHERE id = ?",
            (token_hash, now_iso(), user_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_api_token_hash(user_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT api_token_hash FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return row["api_token_hash"] if row else None
    finally:
        conn.close()


def get_users_with_tokens():
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, api_token_hash FROM users WHERE api_token_hash IS NOT NULL"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --- scores / eligibility ---

def record_score(opportunity_id, user_id, score, components=None):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO scores (opportunity_id, user_id, score, components_json, computed_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (opportunity_id, user_id, score, _dumps(components), now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def record_eligibility(opportunity_id, user_id, status, reasons=None, missing=None):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO eligibility_results (opportunity_id, user_id, status, "
            "reasons_json, missing_information_json, checked_at) VALUES (?, ?, ?, ?, ?, ?)",
            (opportunity_id, user_id, status, _dumps(reasons), _dumps(missing), now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def count_verifications():
    conn = get_connection()
    row = conn.execute("SELECT COUNT(*) FROM verifications").fetchone()
    return int(row[0]) if row else 0


def refresh_deadline_and_trust(limit=None, conn=None):
    """Backfill deadline_status + trust_score for all (or `limit`) opportunities."""
    own = conn is None
    conn = conn or get_connection()
    try:
        sql = "SELECT * FROM opportunities"
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = conn.execute(sql).fetchall()
        for row in rows:
            opp = row_to_opportunity(row)
            conn.execute(
                "UPDATE opportunities SET deadline_status = ?, trust_score = ? WHERE id = ?",
                (_deadlines.status(opp), _trust.compute(opp)[0], opp["id"]),
            )
        if own:
            conn.commit()
        return len(rows)
    finally:
        if own:
            conn.close()


def record_verification(opportunity_id, status, link_status, message=None):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO verifications (opportunity_id, status, link_status, message, checked_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (opportunity_id, status, link_status, message, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


# --- AI assessments (advisory only) ---

def record_ai_assessment(opportunity_id, verdict, reason=None, deadline_guess=None,
                         confidence=None, model=None):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO ai_assessments "
            "(opportunity_id, verdict, reason, deadline_guess, confidence, model, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (opportunity_id, verdict, reason, deadline_guess, confidence, model, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def get_ai_assessment(opportunity_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM ai_assessments WHERE opportunity_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (opportunity_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# --- notifications / deadlines ---

def insert_notification(opportunity_id, kind, message, channel="telegram", delivered=0, user_id=None):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO notifications (opportunity_id, user_id, channel, kind, message, sent_at, delivered) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (opportunity_id, user_id, channel, kind, message, now_iso(), delivered),
        )
        conn.commit()
    finally:
        conn.close()


def list_user_notifications(user_id, limit=50, include_read=False):
    conn = get_connection()
    try:
        sql = (
            "SELECT n.*, o.title, o.deadline_status, o.trust_score, "
            "o.verification_status, o.type "
            "FROM notifications n "
            "LEFT JOIN opportunities o ON o.id = n.opportunity_id "
            "WHERE n.user_id = ?"
        )
        if not include_read:
            sql += " AND n.delivered = 0"
        sql += " ORDER BY n.id DESC LIMIT ?"
        return [dict(r) for r in conn.execute(sql, (user_id, limit)).fetchall()]
    finally:
        conn.close()


def unread_notification_count(user_id):
    conn = get_connection()
    try:
        return int(conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND delivered = 0",
            (user_id,),
        ).fetchone()[0])
    finally:
        conn.close()


def mark_user_notifications_read(user_id, notification_ids=None):
    conn = get_connection()
    try:
        if notification_ids:
            conn.executemany(
                "UPDATE notifications SET delivered = 1 WHERE id = ? AND user_id = ?",
                [(nid, user_id) for nid in notification_ids],
            )
        else:
            conn.execute(
                "UPDATE notifications SET delivered = 1 WHERE user_id = ? AND delivered = 0",
                (user_id,),
            )
        conn.commit()
    finally:
        conn.close()


def record_view(user_id, opportunity_id):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO user_views (user_id, opportunity_id, viewed_at) VALUES (?, ?, ?) "
            "ON CONFLICT (user_id, opportunity_id) "
            "DO UPDATE SET viewed_at = excluded.viewed_at",
            (user_id, opportunity_id, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def recently_viewed(user_id, limit=8):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT o.*, v.viewed_at FROM user_views v "
            "JOIN opportunities o ON o.id = v.opportunity_id "
            "WHERE v.user_id = ? AND o.duplicate_of IS NULL "
            "ORDER BY v.viewed_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def upsert_deadline(opportunity_id, deadline):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO deadlines (opportunity_id, deadline, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT (opportunity_id) DO UPDATE SET deadline = excluded.deadline, updated_at = excluded.updated_at",
            (opportunity_id, deadline, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def mark_deadline_notified(opportunity_id, bucket):
    conn = get_connection()
    try:
        conn.execute(f"UPDATE deadlines SET {bucket} = 1 WHERE opportunity_id = ?", (opportunity_id,))
        conn.commit()
    finally:
        conn.close()


# --- logs / errors / search queries ---

def log_execution(run_id, workflow, step, status, message="", started_at=None, finished_at=None):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO execution_logs (run_id, workflow, step, status, message, started_at, finished_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, workflow, step, status, message, started_at or now_iso(), finished_at),
        )
        conn.commit()
    finally:
        conn.close()


def log_error(component, error_type, message, traceback_text=None):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO system_errors (component, error_type, message, traceback, occurred_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (component, error_type, message, traceback_text, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def insert_search_query(query, engine, result_count):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO search_queries (query, engine, ran_at, result_count) VALUES (?, ?, ?, ?)",
            (query, engine, now_iso(), result_count),
        )
        conn.commit()
    finally:
        conn.close()


# --- discovery observability (Phase 18) ---

DISCOVERY_RUN_COLUMNS = (
    "run_id", "scout", "source_id", "source_name", "source_url", "method",
    "crawler",
    "raw_items", "role_gate", "location_gate", "pattern_gate", "extracted",
    "stored_new", "duplicates", "eligible", "likely_eligible", "unclear",
    "not_eligible", "published", "extraction_errors", "retries",
    "http_status", "response_ms", "error", "started_at", "finished_at",
)


def record_discovery_run(**kwargs):
    cols = [c for c in DISCOVERY_RUN_COLUMNS if c in kwargs]
    conn = get_connection()
    try:
        conn.execute(
            f"INSERT INTO discovery_runs ({', '.join(cols)}) "
            f"VALUES ({', '.join('?' for _ in cols)})",
            [kwargs[c] for c in cols],
        )
        conn.commit()
    finally:
        conn.close()


def record_source_health(source_id, ok, status_code=None, message=None,
                         response_ms=None, consecutive_failures=0,
                         cooldown_until=None):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO source_health "
            "(source_id, ok, status_code, message, response_ms, "
            " consecutive_failures, cooldown_until, checked_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (source_id, 1 if ok else 0, status_code, message, response_ms,
             consecutive_failures, cooldown_until, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def record_filtering_decision(run_id, source_id, stage, title, organization,
                              url, reason):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO filtering_decisions "
            "(run_id, source_id, stage, title, organization, url, reason, decided_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, source_id, stage, title, organization, url, reason, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def record_raw_response(run_id, source_id, source_name, url, status, byte_count,
                        sha256, saved_path):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO raw_responses "
            "(run_id, source_id, source_name, url, status, bytes, sha256, "
            " saved_path, stored_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, source_id, source_name, url, status, byte_count, sha256,
             saved_path, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def set_source_success(source_id):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE sources SET last_success = ?, consecutive_failures = 0, "
            "cooldown_until = NULL, last_checked = ? WHERE id = ?",
            (now_iso(), now_iso(), source_id),
        )
        conn.commit()
    finally:
        conn.close()


def set_source_failure(source_id, error, cooldown_seconds=None):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COALESCE(consecutive_failures, 0) AS n FROM sources WHERE id = ?",
            (source_id,),
        ).fetchone()
        n = (row["n"] if row else 0) + 1
        cooldown = None
        if cooldown_seconds:
            from datetime import timedelta
            cooldown = (datetime.now(timezone.utc) + timedelta(seconds=cooldown_seconds)).isoformat()
        conn.execute(
            "UPDATE sources SET last_failure = ?, consecutive_failures = ?, "
            "cooldown_until = COALESCE(?, cooldown_until), last_checked = ? "
            "WHERE id = ?",
            (now_iso(), n, cooldown, now_iso(), source_id),
        )
        conn.commit()
    finally:
        conn.close()


def source_cooldown_remaining(source_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT cooldown_until FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        if not row or not row["cooldown_until"]:
            return 0
        until = row["cooldown_until"]
        try:
            from datetime import datetime
            delta = datetime.fromisoformat(until) - datetime.now(timezone.utc)
            return max(0, int(delta.total_seconds()))
        except ValueError:
            return 0
    finally:
        conn.close()


def list_recent_discovery_runs(limit=100):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM discovery_runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def deadline_days_active():
    """Days-left for every stored deadline that parses (for queue priority)."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT deadline FROM opportunities").fetchall()
    finally:
        conn.close()
    return [_deadlines.days_left(r["deadline"]) for r in rows if r["deadline"]]


def get_due_verifications(limit=20):
    """Items whose next_verification has passed (or was never set), deadline-first."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM opportunities").fetchall()
    finally:
        conn.close()
    now = now_iso()
    due = []
    for r in rows:
        opp = row_to_opportunity(r)
        nv = opp.get("next_verification")
        if nv is None or nv <= now:
            due.append(opp)
    due.sort(key=lambda o: (
        _deadlines.days_left(o.get("deadline")) is None,
        _deadlines.days_left(o.get("deadline")) or 9999,
    ))
    return due[:limit]


# --- crawl job queue ---

def enqueue_crawl_job(run_id, source_id, source_name, url, crawler, priority="medium"):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO crawl_jobs "
            "(run_id, source_id, source_name, url, crawler, priority, status, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'QUEUED', ?)",
            (run_id, source_id, source_name, url, crawler, priority, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def next_crawl_jobs(limit=10):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM crawl_jobs WHERE status = 'QUEUED' "
            "ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, id "
            "LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def complete_crawl_job(job_id, items_found=0, items_created=0, items_updated=0,
                       duplicates_found=0, status="COMPLETED"):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE crawl_jobs SET status = ?, items_found = ?, items_created = ?, "
            "items_updated = ?, duplicates_found = ?, completed_at = ? WHERE id = ?",
            (status, items_found, items_created, items_updated, duplicates_found,
             now_iso(), job_id),
        )
        conn.commit()
    finally:
        conn.close()


def fail_crawl_job(job_id, error, retry=True):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT retry_count FROM crawl_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        retries = (row["retry_count"] if row else 0) + 1
        status = "RETRYING" if retry and retries < 3 else "FAILED"
        conn.execute(
            "UPDATE crawl_jobs SET status = ?, retry_count = ?, error = ?, "
            "completed_at = ? WHERE id = ?",
            (status, retries, str(error)[:500], now_iso(), job_id),
        )
        conn.commit()
    finally:
        conn.close()


def list_crawl_jobs(limit=50, status=None):
    conn = get_connection()
    try:
        sql = "SELECT * FROM crawl_jobs"
        params = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def crawl_queue_stats():
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT status, COUNT(*) n FROM crawl_jobs GROUP BY status"
        ).fetchall()
        return {r["status"]: r["n"] for r in rows}
    finally:
        conn.close()


def retry_crawl_job(job_id):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE crawl_jobs SET status = 'QUEUED', error = NULL, completed_at = NULL "
            "WHERE id = ?", (job_id,),
        )
        conn.commit()
    finally:
        conn.close()


def expire_stale_crawl_jobs(max_age_hours=6, now=None):
    """Mark ancient QUEUED jobs FAILED so a crashed run cannot block enqueueing.

    Uses fail_crawl_job semantics so the retry budget is respected.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=max_age_hours)).isoformat()
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id FROM crawl_jobs WHERE status = 'QUEUED' AND started_at < ?",
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()
    expired = 0
    for row in rows:
        fail_crawl_job(row["id"], f"stale job (> {max_age_hours}h queued)")
        expired += 1
    return expired


def reactivate_retrying_crawl_jobs():
    """RETRYING jobs from earlier runs get a fresh QUEUED attempt."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE crawl_jobs SET status = 'QUEUED', started_at = ?, "
            "completed_at = NULL WHERE status = 'RETRYING'",
            (now_iso(),),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def list_discovery_runs_for_run(run_id, limit=1000):
    """All discovery_runs rows recorded under one pipeline run_id."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM discovery_runs WHERE run_id = ? ORDER BY id LIMIT ?",
            (run_id, int(limit)),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def set_source_enabled(source_id, enabled):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE sources SET enabled = ? WHERE id = ?",
            (1 if enabled else 0, source_id),
        )
        conn.commit()
    finally:
        conn.close()


def count_users():
    conn = get_connection()
    try:
        return int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
    finally:
        conn.close()


def count_sources(enabled_only=False):
    conn = get_connection()
    try:
        sql = "SELECT COUNT(*) FROM sources"
        if enabled_only:
            sql += " WHERE enabled = 1"
        return int(conn.execute(sql).fetchone()[0])
    finally:
        conn.close()


# --- reports (incorrect information) ---

def add_report(opportunity_id, reporter_id, reason, notes=None):
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO reports (opportunity_id, reporter_id, reason, notes, status, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (opportunity_id, reporter_id, reason, notes, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_reports(status="pending"):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT r.*, o.title, o.organization FROM reports r "
            "LEFT JOIN opportunities o ON o.id = r.opportunity_id "
            "WHERE r.status = ? ORDER BY r.id DESC", (status,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def resolve_report(report_id, resolution="accepted"):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE reports SET status = ?, resolved_at = ? WHERE id = ?",
            (resolution, now_iso(), report_id),
        )
        conn.commit()
    finally:
        conn.close()


# --- Rudra chat ---

def add_chat_message(user_id, role, content, provider=None, conversation_id=None):
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO chat_messages (user_id, role, content, provider, "
            "conversation_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, role, content, provider, conversation_id, now_iso()),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_latest_conversation_id(user_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT conversation_id FROM chat_messages WHERE user_id = ? AND "
            "conversation_id IS NOT NULL ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return row["conversation_id"] if row else None
    finally:
        conn.close()


def get_chat_history(user_id, limit=60, conversation_id=_SENTINEL):
    """Messages for a conversation (default: the latest one).

    Legacy rows without a conversation id are treated as one implicit
    conversation so pre-widget history keeps rendering.
    """
    conn = get_connection()
    try:
        if conversation_id is _SENTINEL or conversation_id is None:
            row = conn.execute(
                "SELECT conversation_id FROM chat_messages WHERE user_id = ? "
                "ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            if not row:
                return []
            conversation_id = row["conversation_id"]
        rows = conn.execute(
            "SELECT id, role, content, provider, conversation_id, feedback, created_at "
            "FROM chat_messages WHERE user_id = ? AND conversation_id IS ? "
            "ORDER BY id DESC LIMIT ?",
            (user_id, conversation_id, limit),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]
    finally:
        conn.close()


def clear_chat_history(user_id):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM chat_messages WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


def delete_conversation(user_id, conversation_id):
    """Delete ONE conversation's messages (scoped to its owner)."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM chat_messages WHERE user_id = ? AND conversation_id IS ?",
            (user_id, conversation_id),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def set_message_feedback(user_id, message_id, feedback):
    """Store explicit feedback on the user's OWN assistant message.

    feedback: 'up' | 'down' | None (clears). Returns True when a row changed.
    """
    if feedback not in ("up", "down", None):
        raise ValueError(f"invalid feedback: {feedback!r}")
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE chat_messages SET feedback = ? WHERE id = ? AND user_id = ?",
            (feedback, message_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# --- Agent system helpers ---

def record_agent_metric(agent_id, metric_name, metric_value):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO agent_metrics (agent_id, metric_name, metric_value, recorded_at) "
            "VALUES (?, ?, ?, ?)",
            (agent_id, metric_name, metric_value, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def get_agent_task_stats(agent_id=None):
    conn = get_connection()
    try:
        if agent_id:
            rows = conn.execute(
                "SELECT agent_id, status, COUNT(*) as cnt, AVG(duration_ms) as avg_duration "
                "FROM agent_tasks WHERE agent_id = ? GROUP BY agent_id, status",
                (agent_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT agent_id, status, COUNT(*) as cnt, AVG(duration_ms) as avg_duration "
                "FROM agent_tasks GROUP BY agent_id, status"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_agent_event_counts():
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT agent_id, COUNT(*) as cnt FROM agent_events GROUP BY agent_id"
        ).fetchall()
        return {r["agent_id"]: r["cnt"] for r in rows}
    finally:
        conn.close()


def record_evidence(opportunity_id, field, value, source_url=None,
                    source_text=None, confidence=0.0, agent_id=None):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO opportunity_evidence "
            "(opportunity_id, field, value, source_url, source_text, confidence, agent_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (opportunity_id, field, str(value), source_url, source_text,
             confidence, agent_id, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def get_evidence(opportunity_id, field=None):
    conn = get_connection()
    try:
        if field:
            rows = conn.execute(
                "SELECT * FROM opportunity_evidence WHERE opportunity_id = ? AND field = ? "
                "ORDER BY id DESC",
                (opportunity_id, field),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM opportunity_evidence WHERE opportunity_id = ? ORDER BY id DESC",
                (opportunity_id,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def record_opportunity_change(opportunity_id, change_type, old_value=None, new_value=None):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO opportunity_changes "
            "(opportunity_id, change_type, old_value, new_value, detected_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (opportunity_id, change_type, old_value, new_value, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def get_pending_changes():
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM opportunity_changes WHERE notified = 0 ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()