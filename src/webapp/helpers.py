"""Web app view helpers: personalized scoring, filters, pagination, labels."""
from src import db, scoring, deadlines, schema
from src.notifications import formatting

PAGE_SIZE = 12
PUBLISHABLE_STATUSES = ("eligible", "likely_eligible")


def publishable(status):
    return status in PUBLISHABLE_STATUSES


def score_item(opp, user):
    """Personalized in-memory score + eligibility for a user (read-only).

    The shared match_score/eligibility_status columns belong to the pipeline's
    default user; web visitors get their own per-profile numbers.
    """
    if user:
        try:
            breakdown = scoring.score_breakdown(opp, user)
            return (
                breakdown["overall"],
                breakdown["status"],
                breakdown["reasons"] or [],
                breakdown["missing"] or [],
                breakdown,
            )
        except Exception:
            pass
    return (
        opp.get("match_score"),
        opp.get("eligibility_status"),
        [],
        [],
        None,
    )


def score_items(items, user, by_score=True):
    scored = [(score_item(opp, user), opp) for opp in items]
    if by_score:
        scored.sort(key=lambda pair: (pair[0][0] is None, -(pair[0][0] or 0)))
    return [(opp, score, status, reasons, missing, breakdown)
            for (score, status, reasons, missing, breakdown), opp in scored]


def classify(item):
    """Map an opportunity to Arjun's (internship) or Vidya's (fellowship) lane."""
    stored = str(item.get("type") or "").lower()
    inferred = schema.infer_type(
        item.get("title"), item.get("description"), item.get("category")
    )
    opp_type = inferred or (stored if stored in schema.OPPORTUNITY_TYPES else None)
    if opp_type in schema.VIDYA_TYPES:
        return "fellowship"
    return "internship"


def filter_items(items, query=None, opp_type=None, statuses=None, eligibility=None,
                 active_only=True, country=None, remote=None, verified_only=False):
    q = (query or "").strip().lower()
    ft_ids = db.fts_search_ids(q) if q else None
    country = (country or "").strip().lower()
    result = []
    for opp in items:
        if active_only and not deadlines.is_active(opp):
            continue
        if opp_type:
            if opp_type in ("internship", "fellowship"):
                if classify(opp) != opp_type:
                    continue
            else:
                stored = str(opp.get("type") or "").lower()
                inferred = schema.infer_type(
                    opp.get("title"), opp.get("description"), opp.get("category")
                )
                exact = stored if stored in schema.OPPORTUNITY_TYPES else None
                if opp_type not in (exact, inferred or ""):
                    continue
        if statuses and opp.get("status") not in statuses:
            continue
        if eligibility and opp.get("eligibility_status") not in eligibility:
            continue
        if verified_only and (opp.get("trust_score") or 0) < 60:
            continue
        if remote and not opp.get("remote"):
            continue
        if country and country not in str(opp.get("country") or "").lower() \
                and country not in str(opp.get("location") or "").lower():
            continue
        if q:
            if ft_ids:
                if opp.get("id") not in ft_ids:
                    continue
            elif not any(
                q in str(opp.get(key) or "").lower()
                for key in ("title", "organization", "location", "description")
            ):
                continue
        result.append(opp)
    return result


def sort_items(items, sort):
    """In-place sort for deadline/newest; 'score'/'relevance' keeps order
    (score_items() handles score ordering with by_score=True)."""
    if sort == "deadline":
        items.sort(key=lambda opp: (formatting.deadline_days_left(opp.get("deadline")) or 9999))
    elif sort == "newest":
        items.sort(key=lambda opp: (opp.get("first_seen") or ""), reverse=True)
    return items


def paginate(items, page):
    page = max(1, int(page or 1))
    start = (page - 1) * PAGE_SIZE
    page_items = items[start:start + PAGE_SIZE]
    pages = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
    return page_items, page, pages, len(items)


def deadline_soon(opp):
    days = formatting.deadline_days_left(opp.get("deadline"))
    return days is not None and 0 <= days <= 14


def deadline_days(opp):
    return deadlines.days_left(opp.get("deadline"))


def apply_url(opp):
    return (
        opp.get("application_url")
        or opp.get("official_url")
        or opp.get("source_url")
    )
