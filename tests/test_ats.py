import json
from pathlib import Path

from src.discovery import ats, internship_scout

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def _amazon_job(country_code, location, title="Engineering Intern", is_intern=True):
    return {
        "id": f"job-{location}",
        "title": title,
        "location": location,
        "country_code": country_code,
        "url_next_step": f"https://account.amazon.jobs/jobs/{location}/apply",
        "description_short": "Short description.",
        "posted_date": "July 22, 2026",
        "team": "AWS",
        "is_intern": is_intern,
    }


def test_amazon_parsing_marks_india_and_skips_bad_rows():
    data = {"hits": 3, "jobs": [
        _amazon_job("IN", "KA, Bengaluru", "Software Development Engineer Intern"),
        _amazon_job("US", "WA, Seattle", "Engineering Intern"),
        _amazon_job("MX", "DIF, Mexico City"),
        {"id": "broken", "title": None, "location": "X"},
    ]}
    entries = ats.parse_amazon(data)
    assert len(entries) == 3
    india = next(e for e in entries if "Bengaluru" in e["location"])
    assert india["location"].startswith("India, ")
    assert india["employment_type"] == "internship"
    seattle = next(e for e in entries if "Seattle" in e["location"])
    assert seattle["employment_type"] == "internship"
    assert all(e["title"] and e["url"] for e in entries)


def test_amazon_non_intern_job_has_null_employment_type():
    entries = ats.parse_amazon({"jobs": [_amazon_job("IN", "KA, Bengaluru", "Full-Time Engineer", is_intern=False)]})
    assert entries[0]["employment_type"] is None


def test_location_filter_keeps_only_india_and_remote():
    source = {"method": "ats_greenhouse"}
    locations = [
        ("India, KA, Bengaluru", False, True),
        ("Remote", True, True),
        ("Bengaluru, India", False, True),
        ("San Francisco, CA", False, False),
        ("New York, NY (HQ) (remote)", False, True),
        ("London, UK", False, False),
    ]
    for location, remote, expected in locations:
        entry = {"title": "Intern", "url": "https://x.com/apply",
                 "location": location, "remote": remote}
        result = internship_scout._passes_location_filter(entry, source, internship_scout.INDIA_LOCATION_PATTERNS)
        assert result is expected, f"{location!r} remote={remote} -> {result}"


def test_location_filter_skips_non_ats_sources():
    source = {"method": "rss"}
    entry = {"title": "Intern", "url": "https://x.com/apply", "location": "Somewhere"}
    assert internship_scout._passes_location_filter(entry, source, internship_scout.INDIA_LOCATION_PATTERNS) is True
