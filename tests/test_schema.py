import pytest

from src import db, schema


def test_normalize_produces_complete_standard_shape():
    opp = schema.normalize_opportunity({"title": "X"})
    for field in schema.TEXT_FIELDS + schema.LIST_FIELDS + schema.BOOL_FIELDS:
        assert field in opp, f"missing field: {field}"
    assert "match_score" in opp and "organization_trust_score" in opp
    assert opp["verification_status"] == "pending"
    assert opp["eligibility_status"] == "unknown"
    assert opp["status"] == "new"
    assert opp["title"] == "X"
    assert opp["deadline"] is None
    assert opp["eligible_countries"] == []
    assert opp["remote"] is False


def test_normalize_drops_unknown_keys():
    opp = schema.normalize_opportunity({"title": "X", "secrets": "hack"})
    assert "secrets" not in opp


def test_normalize_coerces_bad_enum_to_default():
    opp = schema.normalize_opportunity({"title": "X", "type": "totally-bogus"})
    assert opp["type"] == "other"
    opp = schema.normalize_opportunity({"title": "X", "type": "Internship"})
    assert opp["type"] == "internship"


def test_normalize_accepts_single_keyword_fields():
    opp = schema.normalize_opportunity({
        "title": "X", "minimum_gpa": "7.5", "stipend": "$2000/mo", "currency": "USD",
    })
    assert opp["minimum_gpa"] == "7.5"
    assert opp["stipend"] == "$2000/mo"


def test_normalize_bool_coercion():
    for value in (True, 1, "1", "true", "yes"):
        opp = schema.normalize_opportunity({"title": "X", "remote": value})
        assert opp["remote"] is True, value
    for value in (False, 0, "0", "no", ""):
        opp = schema.normalize_opportunity({"title": "X", "remote": value})
        assert opp["remote"] is False, value


def test_normalize_clamps_scores():
    opp = schema.normalize_opportunity({"title": "X", "match_score": 150})
    assert opp["match_score"] == 100.0
    opp = schema.normalize_opportunity({"title": "X", "match_score": "not a number"})
    assert opp["match_score"] is None
    opp = schema.normalize_opportunity({"title": "X", "organization_trust_score": -5})
    assert opp["organization_trust_score"] == 0


def test_validate_ok_on_good_opportunity():
    errors, warnings = schema.validate_opportunity({
        "title": "X", "application_url": "https://example.com",
        "deadline": "2026-09-15", "remote": True, "hybrid": False,
        "match_score": 80, "organization_trust_score": 90,
    })
    assert errors == []
    assert warnings == []


def test_validate_missing_title_is_error():
    errors, warnings = schema.validate_opportunity({})
    assert "title is required" in errors


def test_validate_bad_deadline_is_warning():
    errors, warnings = schema.validate_opportunity({"title": "X", "deadline": "someday soon"})
    assert errors == []
    assert any("deadline" in w for w in warnings)


def test_validate_no_url_is_warning():
    errors, warnings = schema.validate_opportunity({"title": "X"})
    assert any("URL" in w for w in warnings)


def test_validate_remote_and_hybrid_conflict_is_warning():
    errors, warnings = schema.validate_opportunity({"title": "X", "remote": True, "hybrid": True})
    assert any("remote" in w and "hybrid" in w for w in warnings)


def test_db_roundtrip_through_normalize(tmp_db):
    raw = {
        "title": "  XYZ Internship  ",
        "type": "INTERNSHIP",
        "remote": "yes",
        "match_score": "94.5",
        "deadline": "2026-09-15",
        "application_url": "https://example.com/apply",
        "eligible_countries": "India, USA",
        "not_a_real_field": "ignored",
    }
    db.upsert_opportunity(raw)
    opp = db.list_opportunities()[0]
    assert opp["title"] == "XYZ Internship"
    assert opp["type"] == "internship"
    assert opp["remote"] is True
    assert opp["match_score"] == 94.5
    assert opp["eligible_countries"] == ["India", "USA"]
    assert "not_a_real_field" not in opp
    assert opp["eligibility_status"] == "unknown"


def test_db_rejects_empty_title(tmp_db):
    with pytest.raises(ValueError):
        db.upsert_opportunity({})