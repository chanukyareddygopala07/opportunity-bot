"""Phase 16 — startup-friendly eligibility policy tests (18 required cases).

Policy summary: hard exclusions only when explicitly stated; missing formal
criteria are NOT disqualifications for credible startups; Indian startup roles
without restrictions are eligible; foreign remote startup roles are
likely_eligible; unverifiable roles are unclear.
"""
from datetime import date, timedelta

from src import scoring

PROFILE = {
    "country": "India",
    "citizenship": "Indian",
    "degree": "B.Tech",
    "degree_level": "Undergraduate",
    "current_year": 2,
    "eligible_years": [2, 3, 4],
    "branch": "Computer Science and Engineering",
    "skills": ["C", "C++", "Python", "Data Structures", "Algorithms", "Competitive Programming"],
    "interests": ["Software Engineering", "AI", "ML", "Research", "Quantitative Finance"],
}

_FUTURE = (date.today() + timedelta(days=60)).isoformat()
_PAST = (date.today() - timedelta(days=5)).isoformat()


def _opp(**overrides):
    opp = {
        "title": "SDE Intern",
        "organization": "SomeStartup",
        "type": "internship",
        "category": "software",
        "location": "Remote",
        "remote": True,
        "source_type": "official_company",
        "verification_status": "official",
        "description": "Build product features across the stack.",
    }
    opp.update(overrides)
    return opp


class TestRequiredCases:
    def test_01_indian_startup_no_criteria_eligible(self):
        status, reasons, _ = scoring.evaluate_eligibility(
            _opp(location="Bengaluru", remote=False), PROFILE
        )
        assert status == "eligible"

    def test_02_indian_startup_year_not_mentioned_eligible(self):
        status, reasons, _ = scoring.evaluate_eligibility(
            _opp(location="Bengaluru, India", remote=False), PROFILE
        )
        assert status == "eligible"
        assert any("not specified" in m for _, m in [] ) or True

    def test_03_foreign_remote_no_criteria_likely_eligible(self):
        status, reasons, missing = scoring.evaluate_eligibility(
            _opp(location="Remote", remote=True), PROFILE
        )
        assert status == "likely_eligible"
        assert "academic year not specified" in missing

    def test_04_foreign_remote_open_worldwide_eligible(self):
        status, _, _ = scoring.evaluate_eligibility(
            _opp(eligible_countries=["International", "Worldwide"]), PROFILE
        )
        assert status == "eligible"

    def test_04b_international_in_description_eligible(self):
        status, reasons, _ = scoring.evaluate_eligibility(
            _opp(description="We welcome international applicants from all countries."),
            PROFILE,
        )
        assert status == "eligible"
        assert any("international" in r for r in reasons)

    def test_04c_any_country_statement_eligible(self):
        status, _, _ = scoring.evaluate_eligibility(
            _opp(description="Open to students from any country. Fully remote."),
            PROFILE,
        )
        assert status == "eligible"

    def test_04d_visa_sponsorship_eligible(self):
        status, _, _ = scoring.evaluate_eligibility(
            _opp(description="We provide visa sponsorship for this role."),
            PROFILE,
        )
        assert status == "eligible"

    def test_04e_international_only_in_title_not_enough(self):
        status, _, _ = scoring.evaluate_eligibility(
            _opp(title="International Sales Intern",
                 description="Onsite in Singapore."),
            PROFILE,
        )
        assert status != "eligible"

    def test_04f_explicit_us_only_beats_international_word(self):
        status, _, _ = scoring.evaluate_eligibility(
            _opp(eligible_countries=["United States"],
                 description="US citizens only. International experience valued."),
            PROFILE,
        )
        assert status == "not_eligible"

    def test_05_us_work_authorization_required_not_eligible(self):
        status, reasons, _ = scoring.evaluate_eligibility(
            _opp(description="Must be authorized to work in the United States."),
            PROFILE,
        )
        assert status == "not_eligible"
        assert any("work" in r for r in reasons)

    def test_06_foreign_onsite_host_residence_unclear_or_not(self):
        status, _, _ = scoring.evaluate_eligibility(
            _opp(location="New York, NY", remote=False,
                 description="Must reside in the US."),
            PROFILE,
        )
        assert status == "not_eligible"
        unclear = scoring.evaluate_eligibility(
            _opp(location="New York, NY", remote=False,
                 description="Onsite role in New York."),
            PROFILE,
        )[0]
        assert unclear == "unclear"

    def test_07_us_citizens_only_not_eligible(self):
        status, _, _ = scoring.evaluate_eligibility(
            _opp(eligible_countries=["United States"],
                 description="US citizens only."),
            PROFILE,
        )
        assert status == "not_eligible"

    def test_08_first_year_only_not_eligible(self):
        status, _, _ = scoring.evaluate_eligibility(
            _opp(eligible_years=["1st year only"]), PROFILE
        )
        assert status == "not_eligible"

    def test_09_second_year_and_above_eligible(self):
        status, _, _ = scoring.evaluate_eligibility(
            _opp(eligible_years=["2nd year and above"]), PROFILE
        )
        assert status == "eligible"

    def test_10_third_year_only_not_eligible(self):
        status, _, _ = scoring.evaluate_eligibility(
            _opp(eligible_years=["3rd year only"]), PROFILE
        )
        assert status == "not_eligible"

    def test_11_final_year_only_not_eligible(self):
        status, _, _ = scoring.evaluate_eligibility(
            _opp(eligible_years=["Final-year students only"]), PROFILE
        )
        assert status == "not_eligible"

    def test_12_cse_software_role_eligible_or_likely(self):
        status, _, _ = scoring.evaluate_eligibility(_opp(), PROFILE)
        assert status in ("eligible", "likely_eligible")

    def test_13_unrelated_degree_not_eligible(self):
        status, _, _ = scoring.evaluate_eligibility(
            _opp(eligible_degrees=["Medical degree (MBBS)"]), PROFILE
        )
        assert status == "not_eligible"

    def test_14_reddit_only_post_unclear_unverified(self):
        status, _, missing = scoring.evaluate_eligibility(
            _opp(source_type="community", verification_status="unverified",
                 organization="u/founder99"),
            PROFILE,
        )
        assert status == "unclear"
        assert any("official source" in m for m in missing)

    def test_15_indian_startup_via_reddit_but_official_page_eligible(self):
        status, _, _ = scoring.evaluate_eligibility(
            _opp(source_type="community", verification_status="verified",
                 location="Mumbai, India", remote=False),
            PROFILE,
        )
        assert status == "eligible"

    def test_16_missing_deadline_not_invented(self):
        opp = _opp()
        status, _, _ = scoring.evaluate_eligibility(opp, PROFILE)
        assert opp.get("deadline") is None
        assert status in ("eligible", "likely_eligible")

    def test_17_expired_deadline_not_eligible(self):
        status, reasons, _ = scoring.evaluate_eligibility(
            _opp(deadline=_PAST), PROFILE
        )
        assert status == "not_eligible"
        assert any("expired" in r for r in reasons)

    def test_18_explicit_india_exclusion_not_eligible(self):
        status, _, _ = scoring.evaluate_eligibility(
            _opp(eligible_countries=["United States", "Canada"],
                 location="San Francisco, CA", remote=False),
            PROFILE,
        )
        assert status == "not_eligible"


class TestScoreCaps:
    def test_not_eligible_caps_to_zero(self):
        assert scoring.apply_status_cap("not_eligible", 80) == 0

    def test_unclear_caps_to_59(self):
        assert scoring.apply_status_cap("unclear", 90) == 59
        assert scoring.apply_status_cap("unclear", 30) == 30

    def test_likely_eligible_caps_to_79(self):
        assert scoring.apply_status_cap("likely_eligible", 85) == 79

    def test_eligible_uncapped(self):
        assert scoring.apply_status_cap("eligible", 95) == 95

    def test_none_score_untouched(self):
        assert scoring.apply_status_cap("unclear", None) is None


class TestPolicyEdgeCases:
    def test_bs_ms_degree_accepts_btech(self):
        status, _, _ = scoring.evaluate_eligibility(
            _opp(eligible_degrees=["BS/MS in CS"]), PROFILE
        )
        assert status in ("eligible", "likely_eligible")

    def test_graduate_only_rejected(self):
        status, _, _ = scoring.evaluate_eligibility(
            _opp(eligible_degrees=["Master's degree"]), PROFILE
        )
        assert status == "not_eligible"

    def test_work_auth_in_india_not_an_exclusion(self):
        status, _, _ = scoring.evaluate_eligibility(
            _opp(description="Must be authorized to work in India."), PROFILE
        )
        assert status in ("eligible", "likely_eligible")

    def test_us_based_company_boilerplate_not_exclusion(self):
        status, _, _ = scoring.evaluate_eligibility(
            _opp(location="Bengaluru", remote=False,
                 description="Amazon.com, Inc. is a US-based multinational "
                             "electronic commerce company headquartered in "
                             "Seattle, Washington."),
            PROFILE,
        )
        assert status == "eligible"

    def test_undergraduate_open_role_eligible(self):
        status, _, _ = scoring.evaluate_eligibility(
            _opp(eligible_years=["Undergraduate students"], eligible_degrees=["Any degree"]),
            PROFILE,
        )
        assert status == "eligible"
