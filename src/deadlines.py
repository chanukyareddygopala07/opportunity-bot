"""Deadline engine — deterministic, timezone-aware.

Statuses:
    OPEN            — deadline exists and is > CLOSING_SOON_DAYS away
    CLOSING_SOON    — deadline exists and is within CLOSING_SOON_DAYS
    CLOSED          — deadline exists and has passed
    UNKNOWN         — deadline present but not parseable
    NO_DEADLINE     — no deadline recorded (rolling / evergreen)

CLOSED items are never surfaced as active anywhere in the product.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

OPEN = "OPEN"
CLOSING_SOON = "CLOSING_SOON"
CLOSED = "CLOSED"
UNKNOWN = "UNKNOWN"
NO_DEADLINE = "NO_DEADLINE"

CLOSING_SOON_DAYS = 30

DEFAULT_TZ = ZoneInfo("Asia/Kolkata")


def now_in_tz(tz=None):
    """Current datetime in the given timezone (default Asia/Kolkata)."""
    return datetime.now(timezone.utc).astimezone(tz or DEFAULT_TZ)


def days_left(deadline_str, today=None):
    """Whole days between today and the deadline, or None if unparseable."""
    if not deadline_str:
        return None
    today = today or now_in_tz().date()
    try:
        deadline = datetime.fromisoformat(str(deadline_str).strip()).date()
    except (ValueError, TypeError):
        return None
    return (deadline - today).days


def status(opp_or_str, today=None):
    """Deadline status for an opportunity dict or a raw deadline string."""
    if isinstance(opp_or_str, dict):
        deadline_str = opp_or_str.get("deadline")
    else:
        deadline_str = opp_or_str
    if not deadline_str:
        return NO_DEADLINE
    days = days_left(deadline_str, today=today)
    if days is None:
        return UNKNOWN
    if days < 0:
        return CLOSED
    if days <= CLOSING_SOON_DAYS:
        return CLOSING_SOON
    return OPEN


def is_active(opp_or_str, today=None):
    """True if the item is still open for applications."""
    return status(opp_or_str, today=today) != CLOSED


def label(status_value):
    return {
        OPEN: "Open",
        CLOSING_SOON: "Closing soon",
        CLOSED: "Closed",
        UNKNOWN: "Deadline unknown",
        NO_DEADLINE: "Rolling",
    }.get(status_value, status_value or "")