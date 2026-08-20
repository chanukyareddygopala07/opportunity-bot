from src.notifications import onboarding


def test_begin_returns_first_question(monkeypatch):
    monkeypatch.setattr(onboarding, "ONBOARDING", {})
    question = onboarding.begin(123)
    assert "year of study" in question.lower()
    assert 123 in onboarding.ONBOARDING


def test_invalid_year_rejected_and_reasks():
    onboarding.ONBOARDING = {1: {"step": 0, "profile": {}}}
    reply, finished = onboarding.handle_answer(1, "9")
    assert "year" in reply.lower()
    assert finished is False
    assert onboarding.ONBOARDING[1]["step"] == 0


def test_full_flow_persists_profile(monkeypatch):
    saved = {}
    def fake_upsert(profile, chat_id=None):
        saved[chat_id] = profile
    monkeypatch.setattr("src.db.upsert_user", fake_upsert)
    onboarding.ONBOARDING = {}
    onboarding.begin(42)
    replies = []
    for answer in ["2", "B.Tech", "Computer Science", "C, C++, Python", "-"]:
        reply, finished = onboarding.handle_answer(42, answer)
        replies.append(reply)
        if finished:
            break
    assert finished
    profile = saved[42]
    assert profile["current_year"] == 2
    assert profile["degree"] == "B.Tech"
    assert profile["branch"] == "Computer Science"
    assert profile["skills"] == ["C", "C++", "Python"]
    assert "interests" not in profile or not profile["interests"]
    assert 42 not in onboarding.ONBOARDING
    assert "Profile saved" in replies[-1]


def test_skip_marker_for_branch():
    onboarding.ONBOARDING = {7: {"step": 1, "profile": {"current_year": 1}}}
    reply, finished = onboarding.handle_answer(7, "-")
    assert "branch" in reply.lower()
    assert onboarding.ONBOARDING[7]["profile"].get("branch") is None


def test_answer_without_state_is_ignored():
    onboarding.ONBOARDING = {}
    assert onboarding.handle_answer(99, "hello") == (None, False)


def test_is_profile_complete():
    assert not onboarding.is_profile_complete({"current_year": 1})
    assert not onboarding.is_profile_complete(
        {"current_year": 1, "degree": "B.Tech", "skills": []})
    assert onboarding.is_profile_complete(
        {"current_year": 1, "degree": "B.Tech", "skills": ["Python"]})


def test_cancel_clears_state():
    onboarding.ONBOARDING = {3: {"step": 2, "profile": {}}}
    onboarding.cancel(3)
    assert 3 not in onboarding.ONBOARDING