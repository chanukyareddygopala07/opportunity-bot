from src.notifications import formatting


def test_profile_renders_null_fields_as_not_set():
    profile = {
        "country": "India",
        "degree": "B.Tech",
        "current_year": 1,
        "university": None,
        "branch": None,
        "graduation_year": None,
        "skills": ["C", "Python"],
        "interests": ["Quant", "ML"],
        "preferred": {"paid": True, "remote": False},
        "allow": ["paid_internships"],
    }
    text = formatting.profile_to_text(profile)
    assert "India" in text
    assert "B.Tech" in text
    assert text.count("Not set") == 3
    assert "C, Python" in text
    assert "paid" in text


def test_opportunity_renders_with_apply_link():
    opp = {
        "title": "XYZ Research Internship",
        "organization": "XYZ Labs",
        "type": "internship",
        "match_score": 94,
        "eligibility_status": "eligible",
        "funding": "Paid",
        "deadline": "2026-09-15",
        "location": "Remote",
        "remote": True,
        "application_url": "https://example.com/apply",
    }
    text = formatting.opportunity_to_text(opp)
    assert "XYZ Research Internship" in text
    assert "94%" in text
    assert "Eligible" in text
    assert "Deadline: 2026-09-15" in text
    assert "Remote (remote)" in text
    assert "https://example.com/apply" in text
    assert "Not set" not in text


def test_opportunity_hides_unknown_fields():
    opp = {"title": "XYZ Internship", "organization": "XYZ Labs",
           "application_url": "https://example.com/apply"}
    text = formatting.opportunity_to_text(opp)
    assert "Not set" not in text
    assert "Stipend" not in text
    assert "Deadline" not in text
    assert "Location" not in text
    assert "Score" not in text
    assert "unknown" not in text


def test_opportunities_list_is_compact():
    items = [
        {"title": "Alpha Intern", "organization": "ACME",
         "match_score": 85, "deadline": "2026-10-01"},
        {"title": "Beta Intern", "organization": "BETA",
         "match_score": None, "deadline": None},
    ]
    text = formatting.opportunities_to_text(items)
    lines = text.splitlines()
    assert len(lines) == 2
    assert "Alpha Intern" in lines[0]
    assert "85%" in lines[0]
    assert "until 2026-10-01" in lines[0]
    assert "Not set" not in text


def test_opportunities_list_shows_everything_without_limit():
    items = [{"title": f"Opp {i}", "organization": "O",
              "match_score": i} for i in range(25)]
    text = formatting.opportunities_to_text(items)
    assert "Opp 0" in text and "Opp 24" in text
    assert "Showing" not in text
    assert "…and" not in text


def test_opportunities_pagination_header_and_tags():
    items = [
        {"title": "Expired One", "organization": "A", "status": "expired"},
        {"title": "Closed One", "organization": "B", "status": "closed"},
        {"title": "Fresh One", "organization": "C", "status": "new",
         "match_score": 50},
    ]
    text = formatting.opportunities_to_text(items, limit=2, offset=0, total=3)
    assert "Showing 1–2 of 3" in text
    assert "⏳ expired" in text
    assert "Closed One" in text
    second = formatting.opportunities_to_text(items, limit=2, offset=2, total=3)
    assert "Showing 3–3 of 3" in second
    assert "Fresh One" in second


def test_empty_opportunities_state():
    assert "No opportunities found yet" in formatting.opportunities_to_text([])


def test_html_escaping_of_user_content():
    opp = {"title": "<script>alert(1)</script>", "match_score": 60, "application_url": "https://x.com/?a=1&b=2"}
    text = formatting.opportunity_to_text(opp)
    assert "<script>" not in text
    assert "&lt;script&gt;" in text
    assert "&amp;" in text


def test_deadline_days_left():
    assert formatting.deadline_days_left("not-a-date") is None
    assert formatting.deadline_days_left("2020-01-01") < 0


def test_format_listed_variants():
    assert formatting.format_listed("July 31, 2026") == "2026-07-31"
    assert formatting.format_listed("Aug 10, 2026") == "2026-08-10"
    assert formatting.format_listed("2026-08-18") == "2026-08-18"
    assert formatting.format_listed("Wed, 19 Aug 2026 10:00:00 GMT") == "2026-08-19"
    assert formatting.format_listed("") is None
    assert formatting.format_listed(None) is None


def test_priority_emoji_bands():
    assert formatting.priority_emoji(95) == "🔥"
    assert formatting.priority_emoji(85) == "🟢"
    assert formatting.priority_emoji(75) == "🟡"
    assert formatting.priority_emoji(65) == "⚪"
    assert formatting.priority_emoji(50) == "◽"
    assert formatting.priority_emoji(None) == "◽"