"""Controlled tools for the Rudra orchestrator.

Each tool is a pure function scoped to (user_id, explicit arguments). Tools
project data through explicit whitelists — internal columns, other users'
rows and credentials can never leak into a prompt. The orchestrator may only
call tools registered in TOOLS; there is no arbitrary-query escape hatch.
"""
from src import db, deadlines, scoring, trust


def _opp_brief(opp):
    """Public projection of an opportunity (safe for prompts and API)."""
    if not opp:
        return None
    return {
        "id": opp.get("id"),
        "title": opp.get("title"),
        "organization": opp.get("organization"),
        "type": opp.get("type"),
        "category": opp.get("category"),
        "location": opp.get("location"),
        "country": opp.get("country"),
        "remote": bool(opp.get("remote")),
        "deadline": opp.get("deadline"),
        "deadline_status": deadlines.label(deadlines.status(opp)),
        "requirements": opp.get("requirements") or [],
        "eligible_degrees": opp.get("eligible_degrees") or [],
        "eligible_years": opp.get("eligible_years") or [],
        "eligible_branches": opp.get("eligible_branches") or [],
        "minimum_gpa": opp.get("minimum_gpa"),
        "preferred_skills": opp.get("preferred_skills") or [],
        "stipend": opp.get("stipend"),
        "funding": opp.get("funding"),
        "description": (opp.get("description") or "")[:1200],
        "application_url": opp.get("application_url"),
        "official_url": opp.get("official_url"),
        "verification_status": opp.get("verification_status"),
        "trust_label": trust.trust_label(opp.get("trust_score")),
    }


def _profile_summary(user):
    return {
        "degree": user.get("degree"),
        "branch": user.get("branch"),
        "current_year": user.get("current_year"),
        "graduation_year": user.get("graduation_year"),
        "cgpa": user.get("cgpa"),
        "country": user.get("country"),
        "skills": user.get("skills") or [],
        "interests": user.get("interests") or [],
    }


def search_opportunities(user_id, query=None, limit=5, **_):
    from src.webapp import helpers
    items = db.list_opportunities()
    filtered = helpers.filter_items(items, query=query) if query else [
        o for o in items if deadlines.is_active(o)
    ]
    filtered.sort(key=lambda o: o.get("match_score") or 0, reverse=True)
    return {
        "count": len(filtered[:limit]),
        "opportunities": [_opp_brief(o) for o in filtered[:limit]],
    }


def get_opportunity(user_id, opportunity_id=None, **_):
    if not opportunity_id:
        return {"error": "opportunity_id required", "opportunity": None}
    try:
        opportunity_id = int(opportunity_id)
    except (TypeError, ValueError):
        return {"error": "invalid opportunity_id", "opportunity": None}
    opp = db.get_opportunity(opportunity_id)
    return {"opportunity": _opp_brief(opp)} if opp else \
        {"error": "not found", "opportunity": None}


def check_eligibility(user_id, opportunity_id=None, **_):
    if not opportunity_id:
        return {"error": "opportunity_id required"}
    opp = db.get_opportunity(int(opportunity_id))
    if not opp:
        return {"error": "not found"}
    profile = db.get_user_by_id(user_id) or {}
    status, reasons, missing = scoring.evaluate_eligibility(opp, profile)
    return {
        "decision": status,
        "reasons": reasons,
        "missing_information": missing,
        "source": "deterministic rules over the stored record",
    }


def get_match_score(user_id, opportunity_id=None, **_):
    if not opportunity_id:
        return {"error": "opportunity_id required"}
    opp = db.get_opportunity(int(opportunity_id))
    if not opp:
        return {"error": "not found"}
    user = db.get_user_by_id(user_id)
    breakdown = scoring.score_breakdown(opp, user or {})
    return {"breakdown": breakdown}


def get_skill_gaps(user_id, opportunity_id=None, **_):
    if not opportunity_id:
        return {"error": "opportunity_id required"}
    opp = db.get_opportunity(int(opportunity_id))
    if not opp:
        return {"error": "not found"}
    user = db.get_user_by_id(user_id) or {}
    required = [s.lower() for s in (opp.get("preferred_skills") or [])]
    have = {s.lower() for s in (user.get("skills") or [])}
    missing = [s for s in (opp.get("preferred_skills") or [])
               if s.lower() not in have]
    matched = [s for s in (opp.get("preferred_skills") or [])
               if s.lower() in have]
    return {"matched_skills": matched, "missing_skills": missing,
            "required_skills": required}


def analyze_resume(user_id, **_):
    resume = db.get_user_resume(user_id) or {}
    sections = {k: v for k, v in resume.items() if v}
    skills = []
    for row in resume.get("projects") or []:
        for token in str(row.get("skills") or row.get("stack") or "").split(","):
            token = token.strip()
            if token:
                skills.append(token)
    user = db.get_user_by_id(user_id) or {}
    for token in user.get("skills") or []:
        if token not in skills:
            skills.append(token)
    weaknesses = []
    if not resume.get("experience"):
        weaknesses.append("no experience entries recorded")
    if not resume.get("projects"):
        weaknesses.append("no projects recorded")
    if not resume.get("education"):
        weaknesses.append("no education section recorded")
    if not resume.get("contact", {}).get("linkedin"):
        weaknesses.append("no LinkedIn link in contact details")
    if len(skills) < 3:
        weaknesses.append("fewer than 3 skills listed")
    return {
        "sections_present": sorted(sections.keys()),
        "skill_count": len(skills),
        "skills": skills[:30],
        "detected_weaknesses": weaknesses or ["no obvious gaps detected"],
        "note": "heuristic analysis of the resume stored on your profile",
    }


def get_deadlines(user_id, days=14, limit=8, **_):
    items = [o for o in db.list_opportunities() if deadlines.is_active(o)]
    soon = []
    for opp in items:
        left = deadlines.days_left(opp.get("deadline"))
        if left is not None and 0 <= left <= int(days):
            soon.append((left, opp))
    soon.sort(key=lambda pair: pair[0])
    return {
        "within_days": int(days),
        "count": len(soon),
        "deadlines": [
            {**(_opp_brief(opp) or {}), "days_left": left}
            for left, opp in soon[:limit]
        ],
    }


def get_saved_opportunities(user_id, limit=10, **_):
    saved = db.list_bookmarks(user_id)[:limit]
    return {"count": len(saved), "saved": [_opp_brief(o) for o in saved]}


def get_application_status(user_id, **_):
    apps = db.list_applications(user_id)
    by_status = {}
    for app in apps:
        by_status[app["status"]] = by_status.get(app["status"], 0) + 1
    recent = [
        {"title": a.get("title"), "organization": a.get("organization"),
         "status": a.get("status"), "updated_at": a.get("updated_at")}
        for a in apps[:5]
    ]
    return {"total": len(apps), "by_status": by_status, "recent": recent}


TOOLS = {
    "search_opportunities": search_opportunities,
    "get_opportunity": get_opportunity,
    "check_eligibility": check_eligibility,
    "get_match_score": get_match_score,
    "get_skill_gaps": get_skill_gaps,
    "analyze_resume": analyze_resume,
    "get_deadlines": get_deadlines,
    "get_saved_opportunities": get_saved_opportunities,
    "get_application_status": get_application_status,
}

# Argument whitelist per tool: anything else sent/derived is dropped.
TOOL_ARG_SCHEMAS = {
    "search_opportunities": {"query": str, "limit": int},
    "get_opportunity": {"opportunity_id": int},
    "check_eligibility": {"opportunity_id": int},
    "get_match_score": {"opportunity_id": int},
    "get_skill_gaps": {"opportunity_id": int},
    "analyze_resume": {},
    "get_deadlines": {"days": int, "limit": int},
    "get_saved_opportunities": {"limit": int},
    "get_application_status": {},
}


def call_tool(name, user_id, args=None):
    """The ONLY sanctioned entry point for running a tool.

    Validates the tool name against the registry, filters arguments through
    the whitelist with type coercion, caps list sizes, scopes every call to
    the requesting user and never raises into the caller.
    """
    func = TOOLS.get(name)
    if func is None:
        return {"tool": name, "error": "unknown tool"}
    allowed = TOOL_ARG_SCHEMAS.get(name, {})
    safe_args = {}
    for key, expected in allowed.items():
        value = (args or {}).get(key)
        if value is None:
            continue
        try:
            safe_args[key] = expected(value)
        except (TypeError, ValueError):
            continue
    if isinstance(safe_args.get("limit"), int):
        safe_args["limit"] = max(1, min(safe_args["limit"], 10))
    if isinstance(safe_args.get("days"), int):
        safe_args["days"] = max(1, min(safe_args["days"], 90))
    try:
        result = func(user_id, **safe_args)
    except Exception as exc:  # tool failures degrade, never crash the chat
        return {"tool": name, "error": f"tool failed: {type(exc).__name__}"}
    return {"tool": name, "result": result}
