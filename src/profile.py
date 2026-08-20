"""Phase 4 — profile editing rules. Pure functions, no I/O."""

EDITABLE_FIELDS = {
    "country", "degree", "current_year", "university",
    "branch", "graduation_year", "skills", "interests",
}

YEAR_MIN, YEAR_MAX = 2026, 2040


def parse_current_year(value):
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None, f"'{value}' is not a valid number"
    if not 1 <= year <= 6:
        return None, "current year must be between 1 and 6"
    return year, None


def parse_year(value):
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None, f"'{value}' is not a valid year"
    if not YEAR_MIN <= year <= YEAR_MAX:
        return None, f"graduation year must be between {YEAR_MIN} and {YEAR_MAX}"
    return year, None


def parse_list(value, field, max_items=15):
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        return None, f"{field} cannot be empty"
    if len(items) > max_items:
        return None, f"{field} has too many items (max {max_items})"
    return items, None


def apply_field(profile, field, raw_value):
    field = str(field).lower()
    if field not in EDITABLE_FIELDS:
        return None, (
            f"unknown field '{field}'. Editable fields: {', '.join(sorted(EDITABLE_FIELDS))}"
        )
    value = " ".join(raw_value) if isinstance(raw_value, (list, tuple)) else str(raw_value)
    value = value.strip()
    if not value:
        return None, f"'{field}' needs a value"
    if field == "current_year":
        parsed, error = parse_current_year(value)
    elif field == "graduation_year":
        parsed, error = parse_year(value)
    elif field in ("skills", "interests"):
        parsed, error = parse_list(value, field)
    else:
        parsed, error = value, None
    if error:
        return None, error
    updated = dict(profile)
    updated[field] = parsed
    return updated, None