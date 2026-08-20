"""Opportunity type inference + lane classification tests."""
from src import schema
from src.webapp import helpers


def test_infer_exact_keywords():
    assert schema.infer_type("Google Summer of Code 2026") == "open_source_program"
    assert schema.infer_type("2026 Hackathon — Build with AI") == "hackathon"
    assert schema.infer_type("Fulbright Fellowship") == "fellowship"
    assert schema.infer_type("DAAD Scholarship") == "scholarship"
    assert schema.infer_type("Research Grant 2026") == "grant"


def test_infer_from_title_description_and_category():
    assert schema.infer_type("New opportunity", "Annual research internship at IISc") == "research_program"
    assert schema.infer_type("Workshop on Deep Learning") == "workshop"
    assert schema.infer_type("National Olympiad 2026") == "competition"
    assert schema.infer_type("Data Science Conference") == "conference"
    assert schema.infer_type("Full-time Software Engineer", None, "software") == "job"
    assert schema.infer_type("Software Engineer Intern") == "internship"


def test_infer_priority_intern_vs_job():
    assert schema.infer_type("Engineering Intern 2026") == "internship"


def test_infer_none_for_empty():
    assert schema.infer_type(None, None, None) is None
    assert schema.infer_type("") is None


def test_infer_never_guesses_other():
    assert schema.infer_type("Mysterious thing X") is None


def test_all_16_types_covered_by_rules():
    rules = {t for t, _ in schema.TYPE_RULES}
    for t in schema.OPPORTUNITY_TYPES:
        if t == "other":
            continue
        assert t in rules, t


def test_classify_lanes():
    assert helpers.classify({"type": "internship"}) == "internship"
    assert helpers.classify({"type": "fellowship"}) == "fellowship"
    assert helpers.classify({"type": "scholarship"}) == "fellowship"
    assert helpers.classify({"type": "research_program"}) == "fellowship"
    assert helpers.classify({"type": "hackathon"}) == "internship"
    assert helpers.classify({"title": "Fulbright Fellowship"}) == "fellowship"


def test_filter_items_exact_type():
    items = [
        {"id": 1, "type": "internship", "title": "SDE Intern", "deadline": "2099-01-01"},
        {"id": 2, "type": "hackathon", "title": "Hack the Valley", "deadline": "2099-01-01"},
        {"id": 3, "type": "scholarship", "title": "DAAD", "deadline": "2099-01-01"},
    ]
    got = helpers.filter_items(items, opp_type="hackathon", active_only=True)
    assert [o["id"] for o in got] == [2]
    got = helpers.filter_items(items, opp_type="internship", active_only=True)
    assert [o["id"] for o in got] == [1, 2]
    got = helpers.filter_items(items, opp_type="fellowship", active_only=True)
    assert [o["id"] for o in got] == [3]


def test_filter_items_lane_includes_related_types():
    items = [
        {"id": 1, "type": "scholarship", "title": "DAAD", "deadline": "2099-01-01"},
        {"id": 2, "type": "internship", "title": "SDE Intern", "deadline": "2099-01-01"},
    ]
    got = helpers.filter_items(items, opp_type="fellowship", active_only=True)
    assert [o["id"] for o in got] == [1]