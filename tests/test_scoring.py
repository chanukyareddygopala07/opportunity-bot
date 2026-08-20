from src import db, scoring
from src import sources as registry

PROFILE = {
    "country": "India",
    "degree": "B.Tech",
    "current_year": 1,
    "branch": "Computer Science",
    "skills": ["C", "C++", "Python", "Machine Learning", "Data Structures", "Algorithms"],
    "interests": ["Machine Learning", "Quantitative Research", "Software Engineering"],
    "preferred": {"paid": True, "fully_funded": True, "remote": True},
    "allow": ["paid_internships", "research_internships", "fellowships"],
}


def _opp(**overrides):
    opp = {
        "title": "ML Research Intern",
        "organization": "Modal",
        "type": "internship",
        "category": "ai_ml",
        "preferred_skills": ["Python", "Machine Learning"],
        "eligible_degrees": ["b.tech"],
        "eligible_years": ["1st year"],
        "eligible_countries": ["India"],
        "funding": "Stipend provided",
        "stipend": "Rs.10,000/month",
    }
    opp.update(overrides)
    return opp


class TestScoreOpportunity:
    def test_perfect_match_scores_high(self):
        score, breakdown = scoring.score_opportunity(_opp(), PROFILE)
        assert score >= 90
        assert breakdown["skills"] == 25.0
        assert breakdown["interests"] == 20
        assert breakdown["degree"] == 15
        assert breakdown["year"] == 15
        assert breakdown["country"] == 10
        assert breakdown["funding"] == 10

    def test_skills_partial_overlap(self):
        score, breakdown = scoring.score_opportunity(
            _opp(preferred_skills=["Java", "TensorFlow"]), PROFILE
        )
        assert breakdown["skills"] == 0.0

    def test_category_mismatch_scores_zero(self):
        score, breakdown = scoring.score_opportunity(
            _opp(category="security"), PROFILE
        )
        assert breakdown["interests"] == 0
        assert score < 90

    def test_degree_mismatch(self):
        score, breakdown = scoring.score_opportunity(
            _opp(eligible_degrees=["ph.d"]), PROFILE
        )
        assert breakdown["degree"] == 0

    def test_year_mismatch(self):
        score, breakdown = scoring.score_opportunity(
            _opp(eligible_years=["3rd year", "4th year"]), PROFILE
        )
        assert breakdown["year"] == 0

    def test_branch_open_to_all(self):
        score, breakdown = scoring.score_opportunity(
            _opp(eligible_branches=["all branches"]), PROFILE
        )
        assert breakdown["branch"] == 10

    def test_international_open_opportunity(self):
        score, breakdown = scoring.score_opportunity(
            _opp(eligible_countries=["International"]), PROFILE
        )
        assert breakdown["country"] == 10

    def test_missing_info_is_neutral(self):
        score, breakdown = scoring.score_opportunity(
            _opp(preferred_skills=None, eligible_degrees=None, eligible_years=None,
                 eligible_countries=None, funding=None, stipend=None),
            PROFILE,
        )
        assert "skills" not in breakdown
        assert "degree" not in breakdown
        assert "funding" not in breakdown
        assert score is not None

    def test_unpaid_penalized_unless_allowed(self):
        _, breakdown = scoring.score_opportunity(
            _opp(funding="Unpaid"), PROFILE
        )
        assert breakdown["funding"] == 0
        allowed_profile = dict(PROFILE, allow=["paid_internships", "unpaid_internships"])
        _, breakdown = scoring.score_opportunity(
            _opp(funding="Unpaid"), allowed_profile
        )
        assert breakdown["funding"] == 5

    def test_no_comparable_data_returns_none(self):
        score, breakdown = scoring.score_opportunity(
            {"title": "Anything", "organization": "X"}, {}
        )
        assert score is None
        assert breakdown == {}

    def test_type_allow_list(self):
        _, breakdown = scoring.score_opportunity(
            _opp(type="scholarship", category="fellowship"), PROFILE
        )
        assert breakdown["type"] == 0
        fellowship_profile = dict(PROFILE, allow=["fellowships", "scholarships"])
        _, breakdown = scoring.score_opportunity(
            _opp(type="scholarship", category="fellowship"), fellowship_profile
        )
        assert breakdown["type"] == 5


class TestEligibility:
    def test_fully_eligible(self):
        status, reasons, missing = scoring.evaluate_eligibility(_opp(), PROFILE)
        assert status == "eligible"
        assert missing == []

    def test_not_eligible_by_degree(self):
        status, reasons, missing = scoring.evaluate_eligibility(
            _opp(eligible_degrees=["ph.d"]), PROFILE
        )
        assert status == "not_eligible"
        assert any("degree" in r for r in reasons)

    def test_not_eligible_by_country(self):
        status, reasons, missing = scoring.evaluate_eligibility(
            _opp(eligible_countries=["USA"]), PROFILE
        )
        assert status == "not_eligible"
        assert any("country" in r for r in reasons)

    def test_unclear_when_info_missing(self):
        status, reasons, missing = scoring.evaluate_eligibility(
            _opp(eligible_degrees=None, eligible_years=None,
                 eligible_countries=None, eligible_branches=None),
            PROFILE,
        )
        assert status == "unclear"
        assert "official source not found" in missing

    def test_open_country_never_excludes(self):
        status, reasons, missing = scoring.evaluate_eligibility(
            _opp(eligible_countries=["International"]), PROFILE
        )
        assert status == "eligible"


class TestStorage:
    def _seed(self, tmp_db):
        db.upsert_user(dict(PROFILE))
        return db.get_default_user()

    def test_score_for_opportunity_stores_everything(self, tmp_db):
        user = self._seed(tmp_db)
        opp_id = db.upsert_opportunity(_opp())
        score, status = scoring.score_for_opportunity(opp_id, user)
        assert score >= 90
        assert status == "eligible"
        stored = db.get_opportunity(opp_id)
        assert stored["match_score"] == score
        assert stored["eligibility_status"] == "eligible"
        conn = db.get_connection()
        score_row = conn.execute("SELECT * FROM scores WHERE opportunity_id = ?", (opp_id,)).fetchone()
        elig_row = conn.execute(
            "SELECT * FROM eligibility_results WHERE opportunity_id = ?", (opp_id,)
        ).fetchone()
        conn.close()
        assert score_row["score"] == score
        assert score_row["user_id"] == user["id"]
        assert elig_row["status"] == "eligible"

    def test_score_all_updates_every_opportunity(self, tmp_db):
        user = self._seed(tmp_db)
        a = db.upsert_opportunity(_opp())
        b = db.upsert_opportunity(_opp(
            title="Security Research Intern", category="security", funding="Unpaid"
        ))
        count = scoring.score_all(user)
        assert count == 2
        assert db.get_opportunity(a)["match_score"] is not None
        assert db.get_opportunity(b)["match_score"] is not None
        assert db.get_opportunity(a)["eligibility_status"] == "eligible"