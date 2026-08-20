from pathlib import Path

import pytest

from src.extraction import extractor

FIXTURES = Path(__file__).parent / "fixtures"


class TestDeadline:
    def test_keyword_with_iso_date(self):
        text = "Applications close on 2026-12-31 at 5 PM. Apply now."
        assert extractor.find_deadline(text) == "2026-12-31"

    def test_apply_by_with_dmy_date(self):
        text = "Last date of submission: 31 December 2026."
        assert extractor.find_deadline(text) == "2026-12-31"

    def test_mdy_date(self):
        text = "The deadline is December 31, 2026."
        assert extractor.find_deadline(text) == "2026-12-31"

    def test_slash_date_near_keyword(self):
        text = "Due by 31/12/2026 for all applicants."
        assert extractor.find_deadline(text) == "2026-12-31"

    def test_keyword_beats_unrelated_date(self):
        text = "Published on 2026-01-15. The application closes on 31 December 2026."
        assert extractor.find_deadline(text) == "2026-12-31"

    def test_single_date_without_keyword_is_accepted(self):
        text = "This fellowship will end on 30 June 2027."
        assert extractor.find_deadline(text) == "2027-06-30"

    def test_multiple_dates_without_keyword_return_none(self):
        text = "Started on 2026-01-01 and finished on 2026-03-15."
        assert extractor.find_deadline(text) is None

    def test_no_dates_return_none(self):
        assert extractor.find_deadline("No dates here at all.") is None

    def test_invalid_date_is_rejected(self):
        assert extractor.find_deadline("Deadline: 2026-13-40.") is None


class TestDuration:
    def test_keyword_with_months(self):
        assert extractor.find_duration("The duration of the program is 6 months.") == "6 months"

    def test_tenure_weeks(self):
        assert extractor.find_duration("Tenure: 12 weeks.") == "12 weeks"

    def test_single_month(self):
        assert extractor.find_duration("Period of 1 month.") == "1 month"

    def test_spread_over_years(self):
        assert extractor.find_duration("Fellowship spread over 2 years.") == "2 years"

    def test_hyphenated_week_program(self):
        assert extractor.find_duration("A 10-week program.") == "10 weeks"

    def test_plain_number_ignored(self):
        assert extractor.find_duration("There are 6 weeks of content.") is None


class TestStipendAndFunding:
    def test_inr_monthly_stipend(self):
        stipend, currency = extractor.find_stipend(
            "Stipend of Rs. 10,000 per month for selected students."
        )
        assert stipend == "Rs.10,000/month"
        assert currency == "INR"

    def test_dollar_weekly(self):
        stipend, currency = extractor.find_stipend("A stipend of $500 per week is offered.")
        assert stipend == "$500/week"
        assert currency == "USD"

    def test_rupee_symbol_annual(self):
        stipend, currency = extractor.find_stipend("Honorarium of \u20b91,20,000 per annum.")
        assert stipend == "\u20b91,20,000/year"
        assert currency == "INR"

    def test_unpaid_wins_over_paid(self):
        funding, stipend, currency = extractor.find_funding(
            "The role is unpaid, though paid support is possible."
        )
        assert funding == "Unpaid"
        assert stipend is None

    def test_fully_funded(self):
        funding, stipend, currency = extractor.find_funding(
            "This is a fully funded position covering all costs."
        )
        assert funding == "Fully funded"

    def test_stipend_detected_with_currency(self):
        funding, stipend, currency = extractor.find_funding(
            "Stipend of Rs. 10,000 per month is provided."
        )
        assert funding == "Stipend provided"
        assert stipend == "Rs.10,000/month"
        assert currency == "INR"

    def test_no_funding_terms(self):
        assert extractor.find_funding("Just a description with no terms.") == (None, None, None)


class TestGpa:
    def test_cgpa(self):
        assert extractor.find_gpa("Applicants need a CGPA of 7.5 or above.") == "7.5"

    def test_percentage(self):
        assert extractor.find_gpa("Minimum 60% in graduation.") == "60%"

    def test_none(self):
        assert extractor.find_gpa("No marks criteria mentioned.") is None


class TestEligibility:
    def test_degrees(self):
        found = extractor.find_degrees("Open to B.Tech, M.Sc and Ph.D students.")
        assert "b.tech" in found
        assert "m.sc" in found
        assert "ph.d" in found

    def test_years(self):
        found = extractor.find_years("Eligible for 1st year and final year students.")
        assert "1st year" in found
        assert "final year" in found

    def test_branches(self):
        found = extractor.find_branches("Preference for computer science and physics.")
        assert "computer science" in found
        assert "physics" in found

    def test_countries(self):
        found = extractor.find_countries("Open to Indian students and international students.")
        assert "India" in found
        assert "International" in found

    def test_skills(self):
        found = extractor.find_skills(
            "Candidates with Python, machine learning and Docker experience preferred."
        )
        assert "Python" in found
        assert "Machine Learning" in found
        assert "Docker" in found


class TestExtractFields:
    def test_full_extraction(self):
        text = (
            "Applications close on 31 December 2026. The duration is 6 months. "
            "Stipend of Rs. 10,000 per month. CGPA of 7.5 required. "
            "Open to B.Tech students from India in computer science. "
            "Python and machine learning skills preferred."
        )
        fields = extractor.extract_fields(text)
        assert fields["deadline"] == "2026-12-31"
        assert fields["duration"] == "6 months"
        assert fields["funding"] == "Stipend provided"
        assert fields["stipend"] == "Rs.10,000/month"
        assert fields["currency"] == "INR"
        assert fields["minimum_gpa"] == "7.5"
        assert fields["eligible_degrees"] == ["b.tech"]
        assert fields["eligible_branches"] == ["computer science"]
        assert fields["eligible_countries"] == ["India"]
        assert fields["preferred_skills"] == ["Python", "Machine Learning"]

    def test_empty_text_returns_empty_dict(self):
        assert extractor.extract_fields("") == {}
        assert extractor.extract_fields(None) == {}

    def test_garbage_text_leaves_fields_empty(self):
        fields = extractor.extract_fields("Random words without any structured information.")
        assert fields["deadline"] is None
        assert fields["funding"] is None
        assert fields["eligible_degrees"] is None