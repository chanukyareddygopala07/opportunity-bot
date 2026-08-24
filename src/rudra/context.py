"""Context resolution for Rudra chat turns.

The widget sends a *hint* about the current page (never raw data). The server
resolves that hint against its own database, so client-supplied titles,
deadlines or scores can never masquerade as facts. Only minimum-necessary,
whitelisted fields are included.
"""
from src import ai, db
from src.rudra import tools

KNOWN_PAGES = (
    "dashboard", "opportunities", "opportunity", "saved", "applications",
    "resume", "profile", "agents", "resources", "top", "urgent",
)


def resolve_context(user, hint=None):
    """Turn a page hint into trusted context facts for this user only.

    hint: {"page": str, "opportunity_id": int|None}
    Returns a dict safe to embed in prompts / return to the client.
    """
    hint = hint if isinstance(hint, dict) else {}
    page = hint.get("page") or "dashboard"
    if page not in KNOWN_PAGES:
        page = "dashboard"

    context = {
        "page": page,
        "profile": ai.safe_profile(user),
    }

    opportunity_id = hint.get("opportunity_id")
    if page == "opportunity" and opportunity_id:
        result = tools.call_tool("get_opportunity", user["id"],
                                 {"opportunity_id": opportunity_id})
        opp = (result.get("result") or {}).get("opportunity")
        if opp:
            context["opportunity"] = opp
            elig = tools.call_tool("check_eligibility", user["id"],
                                   {"opportunity_id": opportunity_id})
            context["eligibility"] = {
                k: v for k, v in elig.items() if k != "tool"
            }
            match = tools.call_tool("get_match_score", user["id"],
                                    {"opportunity_id": opportunity_id})
            context["match"] = (match.get("result") or {}).get("breakdown") or {}
            gaps = tools.call_tool("get_skill_gaps", user["id"],
                                   {"opportunity_id": opportunity_id})
            context["skill_gaps"] = gaps.get("result") or {}
    elif page == "resume":
        context["resume"] = tools.call_tool("analyze_resume", user["id"]).get("result")
    elif page in ("dashboard", "top", "urgent"):
        context["deadlines_soon"] = tools.call_tool(
            "get_deadlines", user["id"], {"days": 7, "limit": 3}).get("result")

    return context


def _profile_completeness(user):
    fields = ("degree", "branch", "current_year", "graduation_year",
              "university", "country", "cgpa")
    filled = sum(1 for f in fields if user.get(f))
    skills = 1 if (user.get("skills") or []) else 0
    interests = 1 if (user.get("interests") or []) else 0
    total = len(fields) + 2
    return round((filled + skills + interests) / total * 100)


def build_suggestions(user):
    """Deterministic, contextual proactive suggestions (max 3).

    Every suggestion has a stable id so the client can remember dismissals
    and we never nag with the same one.
    """
    suggestions = []
    user_id = user["id"]

    soon = tools.call_tool("get_deadlines", user_id, {"days": 7, "limit": 3})
    soon_result = soon.get("result") or {}
    if soon_result.get("count"):
        top = (soon_result.get("deadlines") or [{}])[0]
        title = top.get("title") or "an opportunity"
        suggestions.append({
            "id": f"closing-soon:{top.get('id')}",
            "text": f"{soon_result['count']} opportunities close within 7 days "
                    f"— next up: {title} ({top.get('days_left')}d). Want a rundown?",
        })

    completeness = _profile_completeness(user)
    if completeness < 100:
        suggestions.append({
            "id": "profile-incomplete",
            "text": f"Your profile is {completeness}% complete — a fuller "
                    "profile means sharper matches. Review it?",
        })

    saved = tools.call_tool("get_saved_opportunities", user_id, {"limit": 10})
    saved_ids = {o.get("id") for o in (saved.get("result") or {}).get("saved") or []}
    applied_rows = db.list_applications(user_id)
    applied = {a.get("opportunity_id") for a in applied_rows}
    saved_not_applied = len(saved_ids - applied)
    if saved_not_applied:
        suggestions.append({
            "id": "saved-not-applied",
            "text": f"You've saved {saved_not_applied} opportunit"
                    f"{'y' if saved_not_applied == 1 else 'ies'} but not started "
                    "any applications yet. Shall we pick one?",
        })
    return suggestions[:3]
