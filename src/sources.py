"""Phase 6 — source registry: config/sources.json <-> sources table.

Add a source by editing config/sources.json — no code changes needed.
Phase 18: sources carry per-source discovery params (max_pages, result_limit,
rate_limit_ms, location_filter, role_patterns) and health state.
"""
import json
from pathlib import Path

from src import db

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
SOURCES_FILE = CONFIG_DIR / "sources.json"

SOURCE_COLUMNS = (
    "name", "organization", "type", "category", "url", "method",
    "priority", "trust_score", "enabled", "check_frequency_hours",
)

JSON_COLUMNS = ("include_patterns", "exclude_patterns", "role_patterns")

_INT_COLUMNS = ("max_pages", "result_limit", "rate_limit_ms")


def _loads(value):
    return json.loads(value) if value else None


def load_config(path=None):
    path = Path(path) if path else SOURCES_FILE
    data = json.loads(path.read_text())
    return data["sources"]


def _int(value, default):
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def sync_sources(sources=None):
    sources = sources if sources is not None else load_config()
    conn = db.get_connection()
    try:
        for src in sources:
            conn.execute(
                """
                INSERT INTO sources (name, organization, type, category, url, method,
                                     priority, trust_score, enabled, check_frequency_hours,
                                     include_patterns, exclude_patterns,
                                     max_pages, result_limit, rate_limit_ms,
                                     location_filter, role_patterns_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (url) DO UPDATE SET
                    name = excluded.name,
                    organization = excluded.organization,
                    type = excluded.type,
                    category = excluded.category,
                    method = excluded.method,
                    priority = excluded.priority,
                    trust_score = excluded.trust_score,
                    enabled = excluded.enabled,
                    check_frequency_hours = excluded.check_frequency_hours,
                    include_patterns = excluded.include_patterns,
                    exclude_patterns = excluded.exclude_patterns,
                    max_pages = excluded.max_pages,
                    result_limit = excluded.result_limit,
                    rate_limit_ms = excluded.rate_limit_ms,
                    location_filter = excluded.location_filter,
                    role_patterns_json = excluded.role_patterns_json
                """,
                (
                    src.get("name"), src.get("organization"), src.get("type"),
                    src.get("category"), src["url"], src.get("method"),
                    src.get("priority", 0), src.get("trust_score", 50),
                    1 if src.get("enabled", True) else 0,
                    src.get("check_frequency_hours", 6),
                    json.dumps(src.get("include_patterns", [])),
                    json.dumps(src.get("exclude_patterns", [])),
                    _int(src.get("max_pages"), 10),
                    _int(src.get("result_limit"), 100),
                    _int(src.get("rate_limit_ms"), 1500),
                    src.get("location_filter", "india_remote"),
                    json.dumps(src.get("role_patterns", [])),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def row_to_source(row):
    src = dict(row)
    for key in JSON_COLUMNS:
        raw = src.get(key + "_json") if key == "role_patterns" else src.get(key)
        src[key] = _loads(raw) if raw else []
    for key in _INT_COLUMNS:
        src[key] = _int(src.get(key), {"max_pages": 10, "result_limit": 100, "rate_limit_ms": 1500}[key])
    src["location_filter"] = src.get("location_filter") or "india_remote"
    return src


def list_enabled_sources(category=None):
    conn = db.get_connection()
    try:
        sql = "SELECT * FROM sources WHERE enabled = 1"
        params = []
        if category:
            sql += " AND (category = ? OR category = 'both')"
            params.append(category)
        rows = conn.execute(sql + " ORDER BY priority, id", params).fetchall()
        return [row_to_source(r) for r in rows]
    finally:
        conn.close()


def mark_checked(source_id):
    conn = db.get_connection()
    try:
        conn.execute("UPDATE sources SET last_checked = ? WHERE id = ?", (db.now_iso(), source_id))
        conn.commit()
    finally:
        conn.close()


def mark_success(source_id):
    db.set_source_success(source_id)


def mark_failure(source_id, error, cooldown_seconds=None):
    db.set_source_failure(source_id, error, cooldown_seconds)


def cooldown_remaining(source_id):
    return db.source_cooldown_remaining(source_id)