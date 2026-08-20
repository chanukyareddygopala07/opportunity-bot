"""Phase 9 — near-duplicate detection for opportunities.

Exact duplicates are already impossible via the unique dedup_key
(title|org|url|deadline). This module catches near-duplicates: the same
program listed with slightly different titles (extra parentheses, commas,
cycle tags). Pure stdlib, offline, no hallucination — a record is only
marked as a duplicate when it is highly similar to an existing one from
the same organization and type, and their deadlines do not conflict.
"""
import re
from difflib import SequenceMatcher

from src import db

SIMILARITY_THRESHOLD = 0.85

PUNCT = re.compile(r"[^\w\s]")
SPACES = re.compile(r"\s+")


def normalize_text(text):
    if not text:
        return ""
    return SPACES.sub(" ", PUNCT.sub(" ", str(text).lower())).strip()


def tokenize(text):
    return normalize_text(text).split()


def token_similarity(a, b):
    ta, tb = tokenize(a), tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(set(ta) & set(tb)) / len(set(ta) | set(tb))


def title_similarity(a, b):
    na, nb = normalize_text(a), normalize_text(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return max(SequenceMatcher(None, na, nb).ratio(), token_similarity(na, nb))


def _deadlines_conflict(deadline_a, deadline_b):
    return bool(deadline_a and deadline_b and deadline_a != deadline_b)


def find_near_duplicates(opportunity_id):
    opp = db.get_opportunity(opportunity_id)
    if not opp or not opp.get("title"):
        return []
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM opportunities "
            "WHERE id != ? AND COALESCE(organization, '') = COALESCE(?, '') "
            "AND type = ? AND duplicate_of IS NULL "
            "ORDER BY first_seen ASC",
            (opportunity_id, opp.get("organization"), opp.get("type")),
        ).fetchall()
    finally:
        conn.close()
    candidates = []
    for row in rows:
        other = db.row_to_opportunity(row)
        if not other.get("title") or other.get("dedup_key") == opp.get("dedup_key"):
            continue
        if _deadlines_conflict(opp.get("deadline"), other.get("deadline")):
            continue
        similarity = title_similarity(opp["title"], other["title"])
        if similarity >= SIMILARITY_THRESHOLD:
            candidates.append((other, round(similarity, 4)))
    candidates.sort(key=lambda item: item[1], reverse=True)
    return candidates


def mark_if_duplicate(opportunity_id):
    """Mark opportunity_id as a duplicate of its best near-duplicate match.

    The older record (earlier first_seen) stays canonical; a missing
    deadline on the canonical record is copied over from the duplicate.
    Returns (duplicate_of_id, similarity) or None.
    """
    candidates = find_near_duplicates(opportunity_id)
    if not candidates:
        return None
    other, similarity = candidates[0]
    opp = db.get_opportunity(opportunity_id)
    if opp and opp.get("duplicate_of"):
        return None
    conn = db.get_connection()
    try:
        conn.execute(
            "UPDATE opportunities SET duplicate_of = ? WHERE id = ? AND duplicate_of IS NULL",
            (other["id"], opportunity_id),
        )
        conn.execute(
            "INSERT INTO duplicates (opportunity_id, duplicate_of_id, similarity, method, detected_at) "
            "VALUES (?, ?, ?, 'title_similarity', ?)",
            (opportunity_id, other["id"], similarity, db.now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    if not other.get("deadline") and opp and opp.get("deadline"):
        db.upsert_deadline(other["id"], opp["deadline"])
    _transfer_links(opportunity_id, other["id"])
    return other["id"], similarity


def _transfer_links(duplicate_id, canonical_id):
    """Carry source links from a duplicate record over to the canonical one so
    multi-source corroboration and review see every source."""
    if duplicate_id == canonical_id:
        return
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO opportunity_sources (opportunity_id, source_id, seen_at) "
            "SELECT ?, source_id, seen_at FROM opportunity_sources WHERE opportunity_id = ?",
            (canonical_id, duplicate_id),
        )
        conn.commit()
    finally:
        conn.close()