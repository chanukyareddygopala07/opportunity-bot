"""Phase 5 — canonical opportunity schema.

Every opportunity entering the system passes through normalize_opportunity(),
so extraction, eligibility, scoring and the DB all speak one standard shape.
Missing information stays null/empty — nothing is ever invented here.
"""
from datetime import datetime

OPPORTUNITY_TYPES = (
    "internship", "fellowship", "scholarship", "research_program",
    "summer_program", "visiting_student_program", "exchange_program",
    "open_source_program", "other",
)

CATEGORIES = (
    "research", "software", "ai_ml", "quant", "finance",
    "data_science", "security", "systems", "biotech", "education", "other",
)

VERIFICATION_STATUSES = ("verified", "official", "unverified", "pending")
ELIGIBILITY_STATUSES = ("eligible", "likely_eligible", "unclear", "not_eligible", "unknown")
STATUSES = ("new", "seen", "expired", "closed")

TEXT_FIELDS = (
    "title", "organization", "type", "category", "description", "location",
    "country", "deadline", "listed_at", "start_date", "end_date", "duration", "minimum_gpa",
    "stipend", "currency", "funding", "travel_support", "housing_support",
    "application_url", "official_url", "source_url", "source_type",
    "verification_status", "eligibility_status", "status",
)

LIST_FIELDS = (
    "eligible_countries", "eligible_degrees", "eligible_years",
    "eligible_branches", "requirements", "preferred_skills",
)

BOOL_FIELDS = ("remote", "hybrid")


def _coerce_enum(value, allowed, default):
    if value is None:
        return default
    candidate = str(value).strip().lower()
    return candidate if candidate in allowed else default


def _coerce_bool(value):
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y")
    return False


def normalize_opportunity(raw):
    raw = dict(raw or {})
    opp = {}

    for field in TEXT_FIELDS:
        value = raw.get(field)
        opp[field] = str(value).strip() if value is not None and str(value).strip() else None

    for field in LIST_FIELDS:
        value = raw.get(field)
        if isinstance(value, list):
            opp[field] = [str(item).strip() for item in value if str(item).strip()]
        elif isinstance(value, str) and value.strip():
            opp[field] = [item.strip() for item in value.split(",") if item.strip()]
        else:
            opp[field] = []

    for field in BOOL_FIELDS:
        opp[field] = _coerce_bool(raw.get(field))

    trust = raw.get("organization_trust_score")
    if trust is not None:
        try:
            opp["organization_trust_score"] = max(0, min(100, int(trust)))
        except (TypeError, ValueError):
            opp["organization_trust_score"] = None
    else:
        opp["organization_trust_score"] = None

    score = raw.get("match_score")
    if score is not None:
        try:
            opp["match_score"] = max(0.0, min(100.0, float(score)))
        except (TypeError, ValueError):
            opp["match_score"] = None
    else:
        opp["match_score"] = None

    opp["first_seen"] = None
    opp["last_seen"] = None
    opp["saved"] = False

    opp["type"] = _coerce_enum(raw.get("type"), OPPORTUNITY_TYPES, "other")
    opp["category"] = _coerce_enum(raw.get("category"), CATEGORIES, "other")
    opp["verification_status"] = _coerce_enum(
        raw.get("verification_status"), VERIFICATION_STATUSES, "pending"
    )
    opp["eligibility_status"] = _coerce_enum(
        raw.get("eligibility_status"), ELIGIBILITY_STATUSES, "unknown"
    )
    opp["status"] = _coerce_enum(raw.get("status"), STATUSES, "new")
    return opp


def validate_opportunity(opp):
    errors, warnings = [], []
    if not opp.get("title"):
        errors.append("title is required")
    url = opp.get("application_url") or opp.get("official_url") or opp.get("source_url")
    if not url:
        warnings.append("no application/official/source URL")
    if opp.get("deadline"):
        try:
            datetime.fromisoformat(str(opp["deadline"]).replace("Z", "+00:00"))
        except ValueError:
            warnings.append(f"deadline not ISO-parseable: {opp['deadline']}")
    if opp.get("remote") and opp.get("hybrid"):
        warnings.append("both remote and hybrid set")
    if opp.get("match_score") is not None and not 0 <= opp["match_score"] <= 100:
        errors.append("match_score out of range 0-100")
    if opp.get("organization_trust_score") is not None and not 0 <= opp["organization_trust_score"] <= 100:
        warnings.append("organization_trust_score out of range 0-100")
    return errors, warnings