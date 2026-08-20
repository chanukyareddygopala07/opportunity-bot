from src import db, profile, store


def test_parse_current_year_bounds():
    assert profile.parse_current_year("1") == (1, None)
    assert profile.parse_current_year("6") == (6, None)
    assert profile.parse_current_year("0")[1] is not None
    assert profile.parse_current_year("7")[1] is not None
    assert profile.parse_current_year("abc")[1] is not None


def test_parse_graduation_year_bounds():
    assert profile.parse_year("2029") == (2029, None)
    assert profile.parse_year("2020")[1] is not None
    assert profile.parse_year("2050")[1] is not None


def test_parse_list():
    items, error = profile.parse_list(" C, C++, Python ", "skills")
    assert items == ["C", "C++", "Python"]
    assert error is None
    assert profile.parse_list("", "skills")[1] is not None
    assert profile.parse_list(", ,", "skills")[1] is not None


def test_apply_field_unknown_field():
    updated, error = profile.apply_field({}, "pizza", "extra cheese")
    assert updated is None
    assert "unknown field" in error


def test_apply_field_text_and_join():
    updated, error = profile.apply_field({}, "university", ["IIT", "Bombay"])
    assert updated["university"] == "IIT Bombay"
    updated, error = profile.apply_field({}, "branch", "Computer Science")
    assert updated["branch"] == "Computer Science"


def test_apply_field_list_conversion():
    updated, error = profile.apply_field({}, "skills", "C, C++, Python")
    assert updated["skills"] == ["C", "C++", "Python"]
    updated, error = profile.apply_field({}, "interests", "ML")
    assert updated["interests"] == ["ML"]


def test_apply_field_validation_errors():
    updated, error = profile.apply_field({}, "current_year", "9")
    assert error is not None
    updated, error = profile.apply_field({}, "graduation_year", "2035")
    assert updated["graduation_year"] == 2035


def test_update_user_by_chat_roundtrip(tmp_db):
    db.upsert_user({
        "country": "India", "degree": "B.Tech", "current_year": 1,
        "skills": ["C"], "interests": ["ML"],
    }, chat_id="111")
    assert db.update_user_by_chat("111", {
        "university": "IIT Bombay",
        "branch": "CSE",
        "graduation_year": 2029,
        "skills": ["C", "C++", "Python"],
    })
    user = db.get_user_by_chat("111")
    assert user["university"] == "IIT Bombay"
    assert user["branch"] == "CSE"
    assert user["graduation_year"] == 2029
    assert user["skills"] == ["C", "C++", "Python"]


def test_update_user_by_chat_unknown_chat(tmp_db):
    assert db.update_user_by_chat("999", {"university": "X"}) is False


def test_store_load_profile_falls_back_to_default(tmp_db):
    profile_data = store.load_profile()
    assert profile_data["country"] == "India"
    assert profile_data["degree"] == "B.Tech"


def test_store_reset_profile(tmp_db, monkeypatch):
    monkeypatch.setenv("OPP_CONFIG_DIR", "config")
    db.upsert_user({
        "country": "India", "degree": "B.Tech", "current_year": 1,
        "skills": ["C"], "interests": ["ML"],
    }, chat_id="111")
    db.update_user_by_chat("111", {"university": "Bogus University", "skills": ["none"]})
    reset = store.reset_profile("111")
    assert reset["university"] is None or reset["university"] in (None, "")
    assert reset["skills"] == ["C", "C++", "Python", "Data Structures", "Algorithms", "Competitive Programming"]