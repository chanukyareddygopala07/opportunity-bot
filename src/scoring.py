"""Phase 10 — profile-based scoring and eligibility.

Deterministic, explainable, offline. An opportunity scores points per
component only when both the opportunity and the profile carry the relevant
information; missing data is neutral, never penalized. Nothing is guessed.

Eligibility (Phase 16 policy rework): hard exclusions only when the source
EXPLICITLY restricts (expired deadline, countries excluding India,
incompatible degree/branch, incompatible year, explicit work-authorization
requirement). Missing formal criteria are NOT disqualifications for credible
startups: Indian-startup roles with no restriction are 'eligible'; credible
foreign remote startup roles are 'likely_eligible'; unverifiable roles are
'unclear'.

Run manually:   python -m src.scoring
"""
import re
import sys
from datetime import date, datetime
from pathlib import Path

from src import db, store

CATEGORY_INTERESTS = {
    "ai_ml": ["artificial intelligence", "machine learning", "ml", "ai"],
    "software": ["software engineering", "software", "swe"],
    "quant": ["quantitative research", "quant", "finance"],
    "research": ["research", "algorithms"],
    "security": ["security"],
    "data_science": ["data science", "machine learning"],
    "fellowship": ["research", "scholarship", "fellowship"],
    "scholarship": ["scholarship", "fellowship", "research"],
    "summer_program": ["research", "summer"],
    "internship": ["software engineering", "research", "internship"],
}

ALLOW_KEYS = {
    "internship": ("paid_internships", "research_internships", "unpaid_internships"),
    "fellowship": ("fellowships",),
    "scholarship": ("scholarships",),
    "summer_program": ("summer_programs",),
    "research_program": ("research_internships",),
}

YEAR_LABELS = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th"}

# Component weights. 100% is reachable only when every component is
# comparable AND matches — sparse opportunities score proportionally lower.
SKILLS_W, INTERESTS_W = 25, 20
DEGREE_W, YEAR_W = 15, 15
BRANCH_W, COUNTRY_W, FUNDING_W, TYPE_W = 10, 10, 10, 5
TOTAL_WEIGHT = SKILLS_W + INTERESTS_W + DEGREE_W + YEAR_W + BRANCH_W + COUNTRY_W + FUNDING_W + TYPE_W

_NORM = re.compile(r"[^a-z0-9]")


def _norm(value):
    if not value:
        return ""
    return _NORM.sub("", str(value).lower())


def _skill_overlap_ratio(opp_skills, profile_skills):
    opp = {_norm(s) for s in opp_skills if s}
    prof = {_norm(s) for s in profile_skills if s}
    if not opp:
        return None
    if not prof:
        return 0.0
    return len(opp & prof) / len(opp)


def _interest_matches(category, profile_interests):
    keywords = CATEGORY_INTERESTS.get(category)
    if not keywords or not profile_interests:
        return None
    for interest in profile_interests:
        interest = _norm(interest)
        if not interest:
            continue
        for keyword in keywords:
            keyword = _norm(keyword)
            if keyword and (keyword in interest or interest in keyword):
                return True
    return False


_UNDERGRAD = {"btech", "be", "bsc", "ba", "bca"}
_POSTGRAD = {"mtech", "msc", "ma", "mca", "phd"}


def _degree_matches(opp_degrees, profile_degree):
    if not opp_degrees:
        return None
    pd = _norm(profile_degree)
    if not pd:
        return None
    for degree in opp_degrees:
        nd = _norm(degree)
        if not nd:
            continue
        if nd in ("undergraduate", "under-graduate"):
            return pd in _UNDERGRAD or pd.startswith("b")
        if nd in ("postgraduate", "post-graduate", "postgraduate"):
            return pd in _POSTGRAD or pd.startswith(("m", "p"))
        if pd == nd or pd in nd or nd in pd:
            return True
    return False


def _year_matches(opp_years, profile_year):
    if not opp_years:
        return None
    try:
        number = int(str(profile_year).strip())
    except (TypeError, ValueError):
        return None
    label = YEAR_LABELS.get(number)
    if not label:
        return None
    needle = f"{label}year"
    return any(needle in _norm(y) or _norm(y) in needle for y in opp_years if y)


def _branch_matches(opp_branches, profile_branch):
    if not opp_branches:
        return None
    pb = _norm(profile_branch)
    if not pb:
        return None
    for branch in opp_branches:
        nb = _norm(branch)
        if "allbranches" in nb or "anybranch" in nb:
            return True
        if pb == nb or pb in nb or nb in pb:
            return True
    return False


def _country_matches(opp_countries, profile_country):
    if not opp_countries:
        return None
    normalized = {_norm(c) for c in opp_countries if c}
    if "international" in normalized or "allcountries" in normalized:
        return True
    pc = _norm(profile_country)
    return bool(pc and pc in normalized)


# --- startup-friendly eligibility policy (Phase 16) ---

INDIAN_CITY_HINTS = (
    "india", "bengaluru", "bangalore", "hyderabad", "mumbai", "delhi",
    "chennai", "pune", "gurgaon", "gurugram", "noida", "kolkata",
)

SCORE_CAPS = {"not_eligible": 0, "unclear": 59, "likely_eligible": 79}

_WORK_AUTH_RE = re.compile(
    r"(?:authorized|authorised)\s+to\s+work[^.;]*"
    r"|\b(?:us|u\.s\.|united\s+states|canadian|canada|uk|british|european)\b[^.;]{0,60}\b(?:citizens?|residents?|nationals?)\b"
    r"|\b(?:citizens?|residents?|nationals?)\b[^.;]{0,40}\bonly\b"
    r"|\bgreen\s+card\b|\bpermanent\s+resident\b"
    r"|(?:no|without)[^.;]{0,20}sponsorship"
    r"|(?:must|required\s+to)\s+(?:resid|be\s+based|work\s+from)[^.;]{0,50}\b(?:us|u\.s\.|united\s+states|canada|uk|britain)\b"
    r"|\b(?:resid|based)\s+in[^.;]{0,30}\b(?:us|u\.s\.|united\s+states|canada|uk)\b",
    re.IGNORECASE,
)


def _deadline_expired(opp):
    deadline = opp.get("deadline")
    if not deadline:
        return None
    try:
        parsed = datetime.fromisoformat(str(deadline).strip().replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return None
    return "expired" if parsed < date.today() else None


def _parse_min_gpa(raw):
    """Parse a minimum-GPA value into a 10-point CGPA threshold.

    Accepts '7.5', '7.5 CGPA', '80%'/'80 percent' (converted to 8.0) and
    4.0-scale values are left as-is; returns None when unparseable.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    value = float(match.group(1))
    if "%" in text or "percent" in text.lower():
        return round(value / 10.0, 2)
    if value > 10:
        return round(value / 10.0, 2)
    return value


def _gpa_eligibility(opp, profile):
    """eligible | not_eligible | None.

    Explicit minimum_gpa on the opportunity vs the profile's CGPA. A missing
    profile CGPA is neutral (None), never a disqualification."""
    threshold = _parse_min_gpa(opp.get("minimum_gpa"))
    if threshold is None:
        return None
    cgpa = profile.get("cgpa")
    if cgpa is None:
        return None
    try:
        cgpa = float(cgpa)
    except (TypeError, ValueError):
        return None
    return "eligible" if cgpa >= threshold else "not_eligible"


def _degree_eligibility(opp_degrees, profile_degree):
    """eligible | not_eligible | None (no explicit information)."""
    if not opp_degrees:
        return None
    degs = [d for d in (_norm(x) for x in opp_degrees) if d]
    if not degs:
        return None
    unrelated = ("law", "llb", "medical", "mbbs", "nursing", "dental",
                 "pharmacy", "architect", "accountancy")
    if any(any(u in d for u in unrelated) for d in degs):
        return "not_eligible"
    postgrad_only = all(
        any(p in d for p in ("master", "phd", "mba", "mtech", "msc",
                             "postgraduate", "post-graduate"))
        for d in degs
    )
    if postgrad_only:
        return "not_eligible"
    has_undergrad = any(
        any(u in d for u in ("bachelor", "undergraduate", "undergrad",
                             "anydegree", "alldegree", "anyfield", "btech",
                             "engineering", "engineer", "b.e", "b.sc", "b.tech"))
        or d.startswith("b")
        for d in degs
    )
    if has_undergrad:
        return "eligible"
    return None


def _year_eligibility(opp_years, profile_year):
    """eligible | not_eligible | None (year not specified or ambiguous)."""
    if not opp_years:
        return None
    try:
        profile_year = int(profile_year)
    except (TypeError, ValueError):
        return None
    for raw in opp_years:
        text = _norm(raw)
        if not text:
            continue
        has_only = "only" in text
        if has_only:
            if any(k in text for k in ("firstyear", "1st", "freshman")):
                return "not_eligible" if profile_year != 1 else "eligible"
            if any(k in text for k in ("secondyear", "2nd", "sophomore")):
                return "not_eligible" if profile_year != 2 else "eligible"
            if any(k in text for k in ("thirdyear", "3rd", "junior")):
                return "not_eligible" if profile_year != 3 else "eligible"
            if any(k in text for k in ("fourthyear", "4th", "senior",
                                       "finalyear", "final", "graduating")):
                return "not_eligible" if profile_year != 4 else "eligible"
        if any(k in text for k in ("above", "orabove", "andabove", "plus",
                                   "orhigher", "upward", "onwards")):
            if any(k in text for k in ("thirdyear", "3rd", "junior")):
                return "not_eligible" if profile_year < 3 else "eligible"
            if any(k in text for k in ("secondyear", "2nd", "sophomore")):
                return "not_eligible" if profile_year < 2 else "eligible"
            if any(k in text for k in ("fourthyear", "4th", "senior",
                                       "finalyear", "final", "graduating")):
                return "not_eligible" if profile_year < 4 else "eligible"
            return "eligible"
        if any(k in text for k in ("allyear", "anyyear", "undergraduate",
                                   "undergrad", "opentoall")):
            return "eligible"
        if any(k in text for k in ("secondyear", "2nd", "sophomore")):
            return "eligible" if profile_year >= 2 else "not_eligible"
        if any(k in text for k in ("firstyear", "1st", "freshman")):
            return "eligible" if profile_year == 1 else None
        if any(k in text for k in ("thirdyear", "3rd", "junior")):
            return "eligible" if profile_year == 3 else None
        if any(k in text for k in ("fourthyear", "4th", "senior")):
            return "eligible" if profile_year == 4 else None
    return None


def _country_eligibility(opp, profile):
    """eligible (India allowed / open) | not_eligible | None."""
    countries = opp.get("eligible_countries")
    if not countries:
        return None
    normalized = {_norm(c) for c in countries if c}
    if not normalized:
        return None
    if any(any(w in c for w in ("international", "worldwide", "global",
                                "allcountries", "anycountry", "open"))
           for c in normalized):
        return "eligible"
    pc = _norm(profile.get("country"))
    if pc and any(pc in c or c in pc for c in normalized):
        return "eligible"
    return "not_eligible"


def _work_auth_exclusion(opp):
    text = " ".join(filter(None, [
        str(opp.get("description") or ""),
        " ".join(str(x) for x in (opp.get("requirements") or [])),
        " ".join(str(x) for x in (opp.get("eligible_countries") or [])),
    ]))
    if not text:
        return None
    text = re.sub(r"u\.s\.", "us", text, flags=re.IGNORECASE)
    for match in _WORK_AUTH_RE.finditer(text):
        if "india" in match.group(0).lower():
            continue
        return "work authorization required in the host country"
    return None


_OPEN_PATTERNS = (
    "international applicants",
    "international students",
    "international candidates",
    "international hires",
    "open to international",
    "welcome international",
    "applicants from any country",
    "students from any country",
    "candidates from any country",
    "any nationality",
    "all nationalities",
    "no geographic",
    "no geographical",
    "no location restriction",
    "anywhere in the world",
    "around the world",
    "from anywhere",
    "work from anywhere",
    "visa sponsorship",
    "sponsorship available",
    "sponsorship provided",
    "sponsorship offered",
    "we sponsor",
    "we provide sponsorship",
)

_SPONSORED_BY = re.compile(
    r"(?:us|our company|we|employer)[^.;]{0,30}(?:sponsor|provides? sponsorship)",
    re.IGNORECASE,
)


def _international_open(opp):
    """True when the source EXPLICITLY accepts international applicants
    (including via visa sponsorship), so an Indian student is eligible."""
    text = " ".join(filter(None, [
        str(opp.get("description") or ""),
        " ".join(str(x) for x in (opp.get("requirements") or [])),
        " ".join(str(x) for x in (opp.get("eligible_countries") or [])),
    ])).lower()
    if not text:
        return False
    if any(pattern in text for pattern in _OPEN_PATTERNS):
        return True
    return bool(_SPONSORED_BY.search(text))


def _funding_score(opp, profile):
    funding = (opp.get("funding") or "").lower()
    preferred = profile.get("preferred") or {}
    allow = [_norm(a) for a in (profile.get("allow") or [])]
    if not funding and not opp.get("stipend"):
        return None
    if funding == "unpaid":
        return 5 if "unpaidinternships" in allow else 0
    if funding == "fully funded":
        return 10 if preferred.get("fully_funded") else 0
    return 10 if preferred.get("paid", True) else 0


def score_opportunity(opp, profile):
    """Returns (score 0-100 or None when nothing comparable, breakdown dict)."""
    parts, weights = {}, {}

    ratio = _skill_overlap_ratio(
        (opp.get("preferred_skills") or []) + (opp.get("requirements") or []),
        profile.get("skills") or [],
    )
    if ratio is not None:
        parts["skills"] = round(ratio * SKILLS_W, 1)
        weights["skills"] = SKILLS_W

    interests = _interest_matches((opp.get("category") or "").lower(), profile.get("interests") or [])
    if interests is not None:
        parts["interests"] = INTERESTS_W if interests else 0
        weights["interests"] = INTERESTS_W

    degree = _degree_matches(opp.get("eligible_degrees"), profile.get("degree"))
    if degree is not None:
        parts["degree"] = DEGREE_W if degree else 0
        weights["degree"] = DEGREE_W

    year = _year_matches(opp.get("eligible_years"), profile.get("current_year"))
    if year is not None:
        parts["year"] = YEAR_W if year else 0
        weights["year"] = YEAR_W

    branch = _branch_matches(opp.get("eligible_branches"), profile.get("branch"))
    if branch is not None:
        parts["branch"] = BRANCH_W if branch else 0
        weights["branch"] = BRANCH_W

    country = _country_matches(opp.get("eligible_countries"), profile.get("country"))
    if country is not None:
        parts["country"] = COUNTRY_W if country else 0
        weights["country"] = COUNTRY_W

    funding = _funding_score(opp, profile)
    if funding is not None:
        parts["funding"] = funding
        weights["funding"] = FUNDING_W

    opp_type = (opp.get("type") or "").lower()
    allow = [_norm(a) for a in (profile.get("allow") or [])]
    if opp_type in ALLOW_KEYS:
        parts["type"] = TYPE_W if any(_norm(a) in allow for a in ALLOW_KEYS[opp_type]) else 0
        weights["type"] = TYPE_W

    if not weights:
        return None, parts
    score = round(sum(parts.values()) / TOTAL_WEIGHT * 100)
    return max(0, min(100, score)), parts


def evaluate_eligibility(opp, profile):
    """Returns (status, reasons, missing).

    Statuses: eligible | likely_eligible | unclear | not_eligible.
    Hard exclusions apply first and are NEVER inferred — they require an
    explicit statement (expired deadline, countries excluding India,
    incompatible degree/branch, incompatible year, explicit work-authorization
    requirement). Missing criteria are not disqualifications.
    """
    reasons, missing = [], []

    expired = _deadline_expired(opp)
    if expired:
        reasons.append(f"deadline expired: {opp.get('deadline')}")
        return "not_eligible", reasons, missing

    degree = _degree_eligibility(opp.get("eligible_degrees"), profile.get("degree"))
    if degree == "not_eligible":
        reasons.append("degree requirement: " + ", ".join(opp.get("eligible_degrees") or []))
        return "not_eligible", reasons, missing

    year = _year_eligibility(opp.get("eligible_years"), profile.get("current_year"))
    if year == "not_eligible":
        reasons.append("year requirement: " + ", ".join(opp.get("eligible_years") or []))
        return "not_eligible", reasons, missing

    gpa = _gpa_eligibility(opp, profile)
    if gpa == "not_eligible":
        reasons.append(f"CGPA requirement: {opp.get('minimum_gpa')}")
        return "not_eligible", reasons, missing

    country = _country_eligibility(opp, profile)
    if country == "not_eligible":
        reasons.append("country restriction: " + ", ".join(opp.get("eligible_countries") or []))
        return "not_eligible", reasons, missing

    auth = _work_auth_exclusion(opp)
    if auth:
        reasons.append(auth)
        return "not_eligible", reasons, missing

    if degree == "eligible":
        reasons.append("degree requirement met")
    if year == "eligible":
        reasons.append("year requirement met")
    if gpa == "eligible":
        reasons.append("CGPA requirement met")
    if country == "eligible":
        reasons.append("eligible countries include India or are open to international applicants")
    if degree is None:
        missing.append("degree requirement not stated")
    if year is None:
        missing.append("academic year not specified")
    if gpa is None and opp.get("minimum_gpa"):
        missing.append("CGPA requirement not stated")
    if country is None:
        missing.append("eligible countries not stated")

    if _international_open(opp):
        reasons.append("explicitly open to international applicants")
        return "eligible", reasons, missing

    location = (opp.get("location") or "").lower()
    remote = bool(opp.get("remote")) or "remote" in location
    india_based = any(hint in location for hint in INDIAN_CITY_HINTS)
    credible = (
        opp.get("verification_status") in ("official", "verified")
        or (opp.get("source_type") or "").startswith("official")
    )
    relevant = (
        (opp.get("category") or "other") not in ("other",)
        or bool(opp.get("preferred_skills") or opp.get("requirements"))
    )

    if (
        country == "eligible"
        or year == "eligible"
        or degree == "eligible"
        or (india_based and not remote and credible)
    ):
        reasons.append("Indian location or explicit criteria met; no restriction found")
        return "eligible", reasons, missing

    if remote:
        if credible and relevant:
            reasons.append("remote startup role; formal criteria not specified")
            return "likely_eligible", reasons, missing
        missing.append("official source not found")
        return "unclear", reasons, missing

    if not credible:
        missing.append("official source not found")
        return "unclear", reasons, missing

    missing.append("location / work authorization unresolved")
    return "unclear", reasons, missing


def apply_status_cap(status, score):
    """Score caps per the Phase 16 policy: not_eligible = 0, unclear <= 59,
    likely_eligible <= 79, eligible keeps its full score."""
    if score is None:
        return score
    cap = SCORE_CAPS.get(status)
    if cap is None:
        return score
    return min(score, cap)


# Eligibility percentage per status — used for the transparent breakdown
# shown on cards: "Eligibility 100% · Career fit 72% → 86%".
ELIGIBILITY_PCT = {
    "eligible": 100,
    "likely_eligible": 79,
    "unclear": 59,
    "not_eligible": 0,
    None: 0,
}


def score_breakdown(opp, profile):
    """Returns a dict with eligibility_pct, career_fit and overall so the UI
    can show an honest, explainable score instead of a single opaque number.

    Eligibility reflects hard-requirement confidence; career_fit is the
    uncapped component score; overall is the status-capped score the app
    actually uses for ranking and display.
    """
    fit, parts = score_opportunity(opp, profile)
    status, reasons, missing = evaluate_eligibility(opp, profile)
    overall = apply_status_cap(status, fit)
    return {
        "status": status,
        "eligibility_pct": ELIGIBILITY_PCT.get(status, 0),
        "career_fit": fit,
        "overall": overall,
        "parts": parts,
        "reasons": reasons,
        "missing": missing,
    }


def score_for_opportunity(opportunity_id, profile=None):
    profile = profile or store.load_profile()
    opp = db.get_opportunity(opportunity_id)
    if not opp:
        return None
    score, breakdown = score_opportunity(opp, profile)
    status, reasons, missing = evaluate_eligibility(opp, profile)
    capped = apply_status_cap(status, score)
    db.record_score(opportunity_id, profile.get("id"), capped, breakdown)
    db.record_eligibility(opportunity_id, profile.get("id"), status, reasons, missing)
    db.update_opportunity(
        opportunity_id, match_score=capped, eligibility_status=status
    )
    return capped, status


def score_all(profile=None):
    profile = profile or store.load_profile()
    items = db.list_opportunities(exclude_duplicates=False)
    for opp in items:
        score_for_opportunity(opp["id"], profile)
    return len(items)


if __name__ == "__main__":
    db.init_db()
    count = score_all()
    profile = store.load_profile()
    print(f"scored {count} opportunities for user {profile.get('id')} ({profile.get('degree')})")
    for item in db.list_opportunities(limit=5):
        print(f"  {item.get('match_score')}% {item.get('eligibility_status'):12s} {item.get('title', '')[:60]}")
    sys.exit(0)