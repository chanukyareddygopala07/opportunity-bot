"""Guided profile onboarding for Telegram (Phase 16 user-requested rework).

Replaces the complex /set field editing with a simple question-by-question
flow: year of study → degree → branch → skills → interests. Pure functions,
in-memory per-chat state, tests in tests/test_onboarding.py.
"""
import logging

from src import db, profile as profile_rules, store

logger = logging.getLogger(__name__)

SKIP_MARKER = "-"

STEPS = [
    (
        "current_year",
        "What year of study are you in?\nReply 1, 2, 3, 4 or 5.",
    ),
    (
        "degree",
        "What degree are you pursuing?\nExample: B.Tech, B.E., B.Sc, B.A.",
    ),
    (
        "branch",
        "What is your branch or specialization?\nExample: Computer Science, "
        "Electrical (reply - to skip)",
    ),
    (
        "skills",
        "What skills do you know?\nComma-separated, e.g. C, C++, Python, SQL",
    ),
    (
        "interests",
        "What are you interested in?\nComma-separated, e.g. ML, Quant, "
        "Research, Web Dev (reply - to skip)",
    ),
]

CORE_FIELDS = ("current_year", "degree", "skills")

ONBOARDING = {}


def is_profile_complete(profile):
    return all(profile.get(field) for field in CORE_FIELDS)


def begin(chat_id):
    ONBOARDING[chat_id] = {"step": 0, "profile": {}}
    field, question = STEPS[0]
    return question


def cancel(chat_id):
    ONBOARDING.pop(chat_id, None)


def _question_for(step):
    return STEPS[step][1]


def handle_answer(chat_id, text):
    """Process one answer. Returns (reply_text, finished) — when finished the
    profile has been persisted."""
    state = ONBOARDING.get(chat_id)
    if state is None:
        return None, False
    field, _ = STEPS[state["step"]]
    value = text.strip()
    if value.lower() == SKIP_MARKER:
        value = None
    updated = dict(state["profile"])
    if value is not None:
        updated, error = profile_rules.apply_field(updated, field, value)
        if error:
            return f"⚠️ {error}\n\n{_question_for(state['step'])}", False
    state["profile"] = updated
    state["step"] += 1
    if state["step"] >= len(STEPS):
        profile = state["profile"]
        db.upsert_user(profile, chat_id=chat_id)
        ONBOARDING.pop(chat_id, None)
        reply = "✅ Profile saved\n\n" + _profile_summary(profile)
        return reply, True
    return _question_for(state["step"]), False


def _profile_summary(profile):
    lines = []
    lines.append(f"Year: {profile.get('current_year')}")
    lines.append(f"Degree: {profile.get('degree')}")
    lines.append(f"Branch: {profile.get('branch') or 'not set'}")
    lines.append(f"Skills: {', '.join(profile.get('skills') or []) or 'not set'}")
    lines.append(f"Interests: {', '.join(profile.get('interests') or []) or 'not set'}")
    return "\n".join(lines)


def top_opportunities(limit=3):
    items = sorted(
        (o for o in store.load_opportunities() if o.get("match_score") is not None),
        key=lambda o: o["match_score"],
        reverse=True,
    )
    return items[:limit]
