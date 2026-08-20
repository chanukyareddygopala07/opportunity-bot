"""Trust score tests — deterministic 0–100, no AI involved."""
from datetime import date, timedelta

from src import trust, deadlines


def _opp(**overrides):
    base = {
        "title": "Research Intern",
        "organization": "IISc",
        "official_url": "https://iisc.ac.in/research-intern",
        "source_url": "https://iisc.ac.in",
        "source_type": "official",
        "location": "Bengaluru",
        "country": "India",
        "deadline": "2099-12-31",
        "eligibility_status": "eligible",
        "last_seen": (date.today()).isoformat(),
        "duplicate_of": None,
    }
    base.update(overrides)
    return base


def test_perfect_score_is_highly_verified():
    score, label, parts = trust.compute(_opp())
    assert score == 100
    assert label == trust.HIGHLY_VERIFIED
    assert all(parts.values())


def test_weights_total_100():
    parts = trust.components(_opp())
    total = sum(points for name, points in trust._WEIGHTS if parts[name])
    assert total == 100


def test_no_official_url_loses_30():
    score, _, _ = trust.compute(_opp(official_url=None, source_type="aggregator"))
    assert score == 70


def test_official_source_type_counts():
    score, label, _ = trust.compute(_opp(official_url=None, source_type="university"))
    assert score == 100


def test_missing_application_destination_loses_20():
    score, _, _ = trust.compute(
        _opp(application_url=None, official_url=None, source_url=None)
    )
    assert score == 75


def test_unparseable_deadline_loses_15():
    score, _, _ = trust.compute(_opp(deadline="flexible"))
    assert score == 85


def test_no_deadline_loses_15():
    score, _, _ = trust.compute(_opp(deadline=None))
    assert score == 85


def test_no_eligibility_loses_15():
    score, _, _ = trust.compute(_opp(eligibility_status=None, match_score=None))
    assert score == 85


def test_stale_last_seen_loses_10():
    stale = (date.today() - timedelta(days=30)).isoformat()
    score, _, _ = trust.compute(_opp(last_seen=stale))
    assert score == 90


def test_missing_last_seen_loses_10():
    score, _, _ = trust.compute(_opp(last_seen=None))
    assert score == 90


def test_duplicate_loses_5():
    score, _, _ = trust.compute(_opp(duplicate_of=3))
    assert score == 95


def test_sparse_metadata_loses_5():
    score, _, _ = trust.compute(_opp(location=None, country=None))
    assert score == 95


def test_minimal_opportunity():
    score, label, _ = trust.compute({"title": "X", "organization": "Y"})
    assert score == 5
    assert label == trust.LOW_CONFIDENCE


def test_labels():
    assert trust.trust_label(100) == trust.HIGHLY_VERIFIED
    assert trust.trust_label(85) == trust.HIGHLY_VERIFIED
    assert trust.trust_label(84) == trust.VERIFIED
    assert trust.trust_label(60) == trust.VERIFIED
    assert trust.trust_label(59) == trust.NEEDS_VERIFICATION
    assert trust.trust_label(30) == trust.NEEDS_VERIFICATION
    assert trust.trust_label(29) == trust.LOW_CONFIDENCE
    assert trust.trust_label(None) == trust.NEEDS_VERIFICATION


def test_compute_all():
    items = [_opp(), _opp(official_url=None, source_type="aggregator")]
    results = trust.compute_all(items)
    assert len(results) == 2
    assert results[0][1] == 100
    assert results[1][1] == 70