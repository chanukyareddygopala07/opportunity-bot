"""Phase 19 — Aawara eligibility engine v2 tests.

Covers the CGPA hard-requirement, transparent score breakdown and the
NSF-REU citizenship nuance (US-only programs must never be auto-eligible
for Indian students).
"""
from src import scoring

PROFILE = {
    "country": "India",
    "citizenship": "Indian",
    "degree": "B.Tech",
    "degree_level": "Undergraduate",
    "current_year": 2,
    "cgpa": 8.2,
    "branch": "Computer Science and Engineering",
    "skills": ["Python", "C++", "DSA"],
    "interests": ["Artificial Intelligence", "Machine Learning", "Research"],
    "allow": ["paid_internships", "research_internships", "fellowships"],
    "preferred": {"paid": True, "fully_funded": True, "research": True},
}


def _opp(**overrides):
    base = {
        "title": "Summer Research Program",
        "organization": "IISER Pune",
        "description": "Undergraduate research internship in computational biology.",
        "location": "Pune, India",
        "category": "research",
        "type": "fellowship",
        "source_type": "official",
        "verification_status": "official",
        "eligible_degrees": ["undergraduate"],
        "eligible_years": ["2nd year", "3rd year"],
        "eligible_countries": ["India"],
        "minimum_gpa": "7.5",
        "funding": "fully funded",
    }
    base.update(overrides)
    return base


class TestGpaEligibility:
    def test_parse_min_gpa_plain(self):
        assert scoring._parse_min_gpa("7.5") == 7.5
        assert scoring._parse_min_gpa("8 CGPA") == 8.0

    def test_parse_min_gpa_percentage(self):
        assert scoring._parse_min_gpa("80%") == 8.0
        assert scoring._parse_min_gpa("75 percent") == 7.5

    def test_parse_min_gpa_unknown(self):
        assert scoring._parse_min_gpa(None) is None
        assert scoring._parse_min_gpa("") is None
        assert scoring._parse_min_gpa("no requirement") is None

    def test_meets_threshold(self):
        status, reasons, _ = scoring.evaluate_eligibility(_opp(), PROFILE)
        assert status == "eligible"
        assert any("CGPA requirement met" in r for r in reasons)

    def test_below_threshold_hard_exclusion(self):
        opp = _opp(minimum_gpa="8.5")
        status, reasons, _ = scoring.evaluate_eligibility(opp, PROFILE)
        assert status == "not_eligible"
        assert any("CGPA requirement" in r for r in reasons)

    def test_missing_profile_cgpa_is_neutral(self):
        profile = dict(PROFILE)
        profile["cgpa"] = None
        status, _, missing = scoring.evaluate_eligibility(_opp(), profile)
        assert status == "eligible"
        assert any("CGPA requirement not stated" in m for m in missing)

    def test_no_min_gpa_on_opp_is_neutral(self):
        opp = _opp(minimum_gpa=None)
        status, _, _ = scoring.evaluate_eligibility(opp, PROFILE)
        assert status == "eligible"


class TestScoreBreakdown:
    def test_breakdown_shape(self):
        b = scoring.score_breakdown(_opp(), PROFILE)
        assert b["status"] == "eligible"
        assert b["eligibility_pct"] == 100
        assert b["overall"] == scoring.apply_status_cap(b["status"], b["career_fit"])
        assert isinstance(b["parts"], dict)
        assert isinstance(b["reasons"], list)

    def test_not_eligible_capped_at_zero(self):
        opp = _opp(minimum_gpa="9.5")
        b = scoring.score_breakdown(opp, PROFILE)
        assert b["eligibility_pct"] == 0
        assert b["overall"] == 0
        assert b["career_fit"] is not None

    def test_unclear_capped(self):
        opp = _opp(
            eligible_degrees=[], eligible_years=[], eligible_countries=[],
            description="on-site program in Munich",
            location="Munich, Germany",
            source_type="individual",
            verification_status=None,
        )
        b = scoring.score_breakdown(opp, PROFILE)
        assert b["status"] == "unclear"
        assert b["eligibility_pct"] == 59
        assert b["overall"] <= 59


class TestReuNuance:
    def test_reu_us_citizens_only_not_eligible(self):
        opp = _opp(
            description=(
                "NSF REU site at Stanford University. Eligibility limited to "
                "U.S. citizens, nationals or permanent residents."
            ),
            location="Stanford, USA",
            eligible_countries=[],
            eligible_degrees=[],
            eligible_years=[],
        )
        status, reasons, _ = scoring.evaluate_eligibility(opp, PROFILE)
        assert status == "not_eligible"
        assert any("work authorization" in r for r in reasons)

    def test_reu_international_welcome_eligible(self):
        opp = _opp(
            description=(
                "NSF REU site. International students are welcome to apply "
                "and the program sponsors J-1 visas for participants."
            ),
            location="Stanford, USA",
            eligible_countries=[],
            eligible_degrees=[],
            eligible_years=[],
        )
        status, _, _ = scoring.evaluate_eligibility(opp, PROFILE)
        assert status == "eligible"

    def test_reu_silent_is_not_auto_eligible(self):
        opp = _opp(
            description="NSF REU site focused on machine learning research.",
            location="Stanford, USA",
            eligible_countries=[],
            eligible_degrees=[],
            eligible_years=[],
        )
        status, _, _ = scoring.evaluate_eligibility(opp, PROFILE)
        assert status == "unclear"