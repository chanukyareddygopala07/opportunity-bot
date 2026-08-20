from src import db, dedupe


def _insert(title, organization="Figma", deadline=None, type_="internship"):
    return db.upsert_opportunity({
        "title": title,
        "organization": organization,
        "type": type_,
        "application_url": f"https://jobs.example/{title.replace(' ', '-').lower()}",
        "deadline": deadline,
    })


class TestNormalize:
    def test_lowercase_punctuation_and_whitespace(self):
        assert dedupe.normalize_text("  Software Engineer Intern (Winter 2027)! ") == (
            "software engineer intern winter 2027"
        )

    def test_empty(self):
        assert dedupe.normalize_text("") == ""
        assert dedupe.normalize_text(None) == ""


class TestTitleSimilarity:
    def test_identical(self):
        assert dedupe.title_similarity("A", "a") == 1.0

    def test_punctuation_only_difference(self):
        a = "Software Engineer Intern (Winter 2027)"
        b = "Software Engineer Intern, Winter 2027"
        assert dedupe.title_similarity(a, b) >= 0.9

    def test_unrelated_titles(self):
        assert dedupe.title_similarity(
            "ML Research Intern", "Accountant (NYC)"
        ) < dedupe.SIMILARITY_THRESHOLD

    def test_empty_returns_zero(self):
        assert dedupe.title_similarity("", "Anything") == 0.0
        assert dedupe.title_similarity(None, None) == 0.0


class TestFindNearDuplicates:
    def test_marks_near_duplicate_same_org(self, tmp_db):
        first = _insert("Software Engineer Intern (Winter 2027)")
        second = _insert("Software Engineer Intern, Winter 2027")
        candidates = dedupe.find_near_duplicates(second)
        assert [c[0]["id"] for c in candidates] == [first]

    def test_different_org_not_duplicate(self, tmp_db):
        _insert("ML Research Intern", organization="Modal")
        other = _insert("ML Research Intern", organization="Anthropic")
        assert dedupe.find_near_duplicates(other) == []

    def test_different_type_not_duplicate(self, tmp_db):
        _insert("Research Internship 2026", organization="ICTS", type_="internship")
        other = _insert(
            "Research Internship 2026", organization="ICTS", type_="fellowship"
        )
        assert dedupe.find_near_duplicates(other) == []

    def test_conflicting_deadlines_not_duplicate(self, tmp_db):
        _insert("Summer Research Fellowship", deadline="2026-12-31")
        other = _insert("Summer Research Fellowship", deadline="2027-06-30")
        assert dedupe.find_near_duplicates(other) == []

    def test_missing_deadline_does_not_block_duplicate(self, tmp_db):
        first = _insert("Summer Research Fellowship", deadline=None)
        other = _insert("Summer Research Fellowship", deadline="2027-06-30")
        candidates = dedupe.find_near_duplicates(other)
        assert [c[0]["id"] for c in candidates] == [first]

    def test_exact_duplicate_not_self_matched(self, tmp_db):
        first = _insert("Same Title Exactly")
        second = _insert("Same Title Exactly", deadline="2026-09-01")
        candidates = dedupe.find_near_duplicates(second)
        assert [c[0]["id"] for c in candidates] == [first]

    def test_unrelated_titles_not_duplicate(self, tmp_db):
        _insert("Software Engineer Intern")
        other = _insert("Data Scientist")
        assert dedupe.find_near_duplicates(other) == []


class TestMarkIfDuplicate:
    def test_marks_and_logs_duplicate(self, tmp_db):
        first = _insert("Software Engineer Intern (Winter 2027)")
        second = _insert("Software Engineer Intern, Winter 2027")
        result = dedupe.mark_if_duplicate(second)
        assert result is not None
        assert result[0] == first
        assert result[1] >= dedupe.SIMILARITY_THRESHOLD
        row = db.get_opportunity(second)
        assert row["duplicate_of"] == first
        conn = db.get_connection()
        dup = conn.execute("SELECT * FROM duplicates").fetchone()
        conn.close()
        assert dup["opportunity_id"] == second
        assert dup["duplicate_of_id"] == first
        assert dup["method"] == "title_similarity"

    def test_older_record_stays_canonical(self, tmp_db):
        first = _insert("Software Engineer Intern (Winter 2027)")
        second = _insert("Software Engineer Intern, Winter 2027")
        dedupe.mark_if_duplicate(second)
        assert db.get_opportunity(first)["duplicate_of"] is None

    def test_deadline_copied_to_canonical(self, tmp_db):
        first = _insert("Software Engineer Intern (Winter 2027)", deadline=None)
        second = _insert(
            "Software Engineer Intern, Winter 2027", deadline="2026-11-15"
        )
        dedupe.mark_if_duplicate(second)
        conn = db.get_connection()
        row = conn.execute(
            "SELECT deadline FROM deadlines WHERE opportunity_id = ?", (first,)
        ).fetchone()
        conn.close()
        assert row["deadline"] == "2026-11-15"

    def test_not_duplicate_returns_none(self, tmp_db):
        _insert("ML Research Intern", organization="Modal")
        other = _insert("ML Research Intern", organization="Anthropic")
        assert dedupe.mark_if_duplicate(other) is None

    def test_idempotent(self, tmp_db):
        _insert("Software Engineer Intern (Winter 2027)")
        second = _insert("Software Engineer Intern, Winter 2027")
        dedupe.mark_if_duplicate(second)
        assert dedupe.mark_if_duplicate(second) is None
        conn = db.get_connection()
        count = conn.execute("SELECT COUNT(*) FROM duplicates").fetchone()[0]
        conn.close()
        assert count == 1


class TestListingExcludesDuplicates:
    def test_default_excludes_duplicates(self, tmp_db):
        first = _insert("Software Engineer Intern (Winter 2027)")
        second = _insert("Software Engineer Intern, Winter 2027")
        dedupe.mark_if_duplicate(second)
        items = db.list_opportunities()
        ids = {item["id"] for item in items}
        assert first in ids
        assert second not in ids

    def test_can_include_duplicates(self, tmp_db):
        _insert("Software Engineer Intern (Winter 2027)")
        second = _insert("Software Engineer Intern, Winter 2027")
        dedupe.mark_if_duplicate(second)
        items = db.list_opportunities(exclude_duplicates=False)
        assert second in {item["id"] for item in items}