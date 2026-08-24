"""P2 data-quality tests: classification word boundaries, GPA scale handling."""
from src import schema


def _classify(opp):
    from src.agents.classification import ClassificationAgent
    agent = ClassificationAgent()
    result = agent.process({"opportunity": opp})
    return result.data, result.confidence, result.evidence


# --- Classification word-boundary fixes (2.1) ---

def test_ai_not_matched_inside_email():
    data, _, _ = _classify({
        "title": "Scholarship for students",
        "description": "Please email us your details to chair the committee.",
    })
    assert data["field"] != "ai_ml"


def test_cs_not_matched_inside_physics():
    data, _, _ = _classify({
        "title": "Physics Fellowship",
        "description": "Research in condensed matter physics and optics.",
    })
    assert data["field"] != "computer_science"


def test_standalone_ai_token_matches():
    data, confidence, _ = _classify({
        "title": "AI Research Intern",
        "description": "Work on ai and machine learning systems.",
    })
    assert data["field"] == "ai_ml"
    assert confidence >= 0.65


def test_multi_word_keyword_matches():
    data, _, _ = _classify({
        "title": "Research Program",
        "description": "Focus on natural language processing.",
    })
    assert data["field"] == "ai_ml"


def test_confidence_reflects_evidence():
    # Type + field both inferred -> higher confidence than type only.
    strong = _classify({"title": "AI Hackathon", "description": "machine learning"})[1]
    weak = _classify({"title": "Some Event", "description": "come one come all"})[1]
    assert strong > weak


# --- GPA scale normalization (2.4) ---

from src.scoring import _parse_min_gpa, _gpa_eligibility


def test_gpa_4_scale_converted_to_10_point():
    assert _parse_min_gpa("3.5 GPA") == 8.75
    assert _parse_min_gpa("3.0 GPA") == 7.5


def test_gpa_explicit_4_scale_marker():
    assert _parse_min_gpa("3.5/4.0") == 8.75
    assert _parse_min_gpa("3.2 on a scale of 4") is not None


def test_cgpa_values_untouched():
    assert _parse_min_gpa("7.5 CGPA") == 7.5
    assert _parse_min_gpa("8.0") == 8.0
    assert _parse_min_gpa("80%") == 8.0


def test_us_style_threshold_compares_honestly():
    # 3.5 GPA (US) == 8.75 CGPA: an 8.5 student is genuinely below.
    opp = {"minimum_gpa": "3.5 GPA"}
    assert _gpa_eligibility(opp, {"cgpa": 9.2}) == "eligible"
    assert _gpa_eligibility(opp, {"cgpa": 8.5}) == "not_eligible"


def test_missing_profile_cgpa_stays_neutral():
    assert _gpa_eligibility({"minimum_gpa": "3.5 GPA"}, {}) is None
