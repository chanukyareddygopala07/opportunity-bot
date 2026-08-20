"""Deadline engine tests — deterministic, timezone-aware statuses."""
import pytest

from src import deadlines


def test_no_deadline():
    assert deadlines.status({}) == deadlines.NO_DEADLINE
    assert deadlines.status(None) == deadlines.NO_DEADLINE
    assert deadlines.status("") == deadlines.NO_DEADLINE


def test_unparseable_is_unknown():
    assert deadlines.status("soon") == deadlines.UNKNOWN
    assert deadlines.status("tomorrow-ish") == deadlines.UNKNOWN
    assert deadlines.status("2026-13-99") == deadlines.UNKNOWN


def test_open_when_far_away():
    assert deadlines.status({"deadline": "2099-12-31"}) == deadlines.OPEN


def test_closing_soon_within_window():
    assert deadlines.status({"deadline": "2026-09-10"}) == deadlines.CLOSING_SOON
    assert deadlines.status({"deadline": "2026-08-21"}) == deadlines.CLOSING_SOON


def test_closed_when_passed():
    assert deadlines.status({"deadline": "2020-01-01"}) == deadlines.CLOSED
    assert deadlines.status({"deadline": "2026-08-19"}) == deadlines.CLOSED


def test_boundary_exactly_today_is_closing_soon():
    assert deadlines.status({"deadline": "2026-08-20"}) == deadlines.CLOSING_SOON


def test_boundary_31_days_is_open():
    assert deadlines.status({"deadline": "2026-09-20"}) == deadlines.OPEN


def test_is_active_excludes_closed():
    assert deadlines.is_active({"deadline": "2099-01-01"})
    assert deadlines.is_active({"deadline": "2026-09-01"})
    assert not deadlines.is_active({"deadline": "2020-01-01"})
    assert deadlines.is_active({})


def test_custom_today():
    today = __import__("datetime").date(2026, 8, 20)
    assert deadlines.status({"deadline": "2026-08-21"}, today=today) == deadlines.CLOSING_SOON
    assert deadlines.status({"deadline": "2026-09-21"}, today=today) == deadlines.OPEN
    assert deadlines.status({"deadline": "2026-08-19"}, today=today) == deadlines.CLOSED


def test_days_left():
    assert deadlines.days_left("2026-08-21") == 1
    assert deadlines.days_left("2099-01-01") > 0
    assert deadlines.days_left("garbage") is None
    assert deadlines.days_left(None) is None
    assert deadlines.days_left("") is None


def test_timezone_aware():
    now = deadlines.now_in_tz()
    assert now.tzinfo is not None
    assert str(now.tzinfo) == "Asia/Kolkata"
    assert deadlines.now_in_tz().date() == deadlines.now_in_tz(deadlines.DEFAULT_TZ).date()


def test_labels():
    assert deadlines.label(deadlines.OPEN) == "Open"
    assert deadlines.label(deadlines.CLOSING_SOON) == "Closing soon"
    assert deadlines.label(deadlines.CLOSED) == "Closed"
    assert deadlines.label(deadlines.UNKNOWN) == "Deadline unknown"
    assert deadlines.label(deadlines.NO_DEADLINE) == "Rolling"


def test_raw_string_input():
    assert deadlines.status("2020-01-01") == deadlines.CLOSED
    assert deadlines.status("2099-01-01") == deadlines.OPEN