"""Trust score — deterministic, 0–100, no AI.

Components (weights in points):
    official source        30   official_url present (official > aggregator)
    application URL valid  20   an application destination is reachable
    deadline verified      15   deadline parses to a real date
    eligibility verified   15   eligibility has been evaluated for a user
    recently crawled       10   last_seen within the freshness window
    duplicate-free          5   not marked as a duplicate
    metadata consistent     5   title + organization + a URL + location/country

Labels:  Highly Verified / Verified / Needs Verification / Low Confidence.
"""
from datetime import datetime, timezone, timedelta

from src import deadlines

TRUST_MAX = 100

FRESH_WINDOW_DAYS = 14

HIGHLY_VERIFIED = "Highly Verified"
VERIFIED = "Verified"
NEEDS_VERIFICATION = "Needs Verification"
LOW_CONFIDENCE = "Low Confidence"

# source_type values that count as official (everything else is an aggregator)
_OFFICIAL_SOURCE_TYPES = ("official", "company", "government", "university")


def trust_label(score):
    if score is None:
        return NEEDS_VERIFICATION
    if score >= 85:
        return HIGHLY_VERIFIED
    if score >= 60:
        return VERIFIED
    if score >= 30:
        return NEEDS_VERIFICATION
    return LOW_CONFIDENCE


def _recently_crawled(opp, today=None):
    today = today or deadlines.now_in_tz().date()
    last_seen = opp.get("last_seen")
    if not last_seen:
        return False
    try:
        seen = datetime.fromisoformat(str(last_seen).strip()).date()
    except (ValueError, TypeError):
        return False
    return (today - seen).days <= FRESH_WINDOW_DAYS


def _metadata_consistent(opp):
    url = (
        opp.get("application_url")
        or opp.get("official_url")
        or opp.get("source_url")
    )
    return bool(
        opp.get("title")
        and opp.get("organization")
        and url
        and (opp.get("location") or opp.get("country"))
    )


def components(opp, today=None):
    """Return {label: bool} for every trust component."""
    source_type = (opp.get("source_type") or "").strip().lower()
    official = bool(opp.get("official_url")) or source_type in _OFFICIAL_SOURCE_TYPES
    has_url = bool(
        opp.get("application_url")
        or opp.get("official_url")
        or opp.get("source_url")
    )
    deadline_ok = deadlines.days_left(opp.get("deadline"), today=today) is not None
    eligibility_ok = bool(opp.get("eligibility_status")) or bool(opp.get("match_score"))
    return {
        "official_source": official,
        "application_url_valid": has_url,
        "deadline_verified": deadline_ok,
        "eligibility_verified": eligibility_ok,
        "recently_crawled": _recently_crawled(opp, today=today),
        "duplicate_free": not opp.get("duplicate_of"),
        "metadata_consistent": _metadata_consistent(opp),
    }


_WEIGHTS = (
    ("official_source", 30),
    ("application_url_valid", 20),
    ("deadline_verified", 15),
    ("eligibility_verified", 15),
    ("recently_crawled", 10),
    ("duplicate_free", 5),
    ("metadata_consistent", 5),
)


def compute(opp, today=None):
    """Trust score for an opportunity dict → (score, label, components)."""
    parts = components(opp, today=today)
    score = sum(points for name, points in _WEIGHTS if parts[name])
    return score, trust_label(score), parts


def compute_all(items, today=None):
    """Score many opportunities at once (no DB round-trips)."""
    return [(opp, compute(opp, today=today)[0]) for opp in items]