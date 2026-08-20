"""Pure formatting helpers for Telegram messages (unit-testable)."""
import html
from datetime import datetime
from email.utils import parsedate_to_datetime

MISSING = "Not set"

ELIGIBILITY_LABEL = {
    "eligible": "Apply now — Eligible",
    "likely_eligible": "Likely eligible — criteria not specified",
    "unclear": "Unclear — verify before applying",
    "not_eligible": "Not eligible",
}


def eligibility_label(status, opp=None):
    """Notification label per Phase 16 policy."""
    if status == "likely_eligible":
        opp = opp or {}
        remote = bool(opp.get("remote")) or "remote" in str(opp.get("location") or "").lower()
        if remote:
            return "Likely eligible — remote startup; criteria not specified"
        return "Likely eligible — criteria not specified"
    return ELIGIBILITY_LABEL.get(status, "Unclear — verify before applying")


def esc(value):
    if value is None or value == "":
        return MISSING
    return html.escape(str(value))


def _list(value):
    if isinstance(value, list) and value:
        return ", ".join(str(v) for v in value)
    return MISSING


def priority_emoji(score):
    try:
        score = float(score)
    except (TypeError, ValueError):
        return "◽"
    if score >= 90:
        return "🔥"
    if score >= 80:
        return "🟢"
    if score >= 70:
        return "🟡"
    if score >= 60:
        return "⚪"
    return "◽"


def _score_text(score):
    try:
        return f"{float(score):.0f}%"
    except (TypeError, ValueError):
        return None


def format_listed(value):
    """Best-effort date -> 'YYYY-MM-DD' (or readable short date)."""
    if not value:
        return None
    text = str(value).strip()
    for parser in (
        datetime.fromisoformat,
        lambda s: parsedate_to_datetime(s).replace(tzinfo=None),
    ):
        try:
            return parser(text).date().isoformat()
        except (ValueError, TypeError, IndexError, OverflowError):
            continue
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return text[:10].rstrip(",; ")


def eligibility_emoji(status):
    return {
        "eligible": "✅",
        "likely_eligible": "🟩",
        "unclear": "⚠️",
        "unknown": "⚠️",
        "not_eligible": "❌",
    }.get(status or "", "❔")


def start_text():
    return (
        "<b>Opportunity Bot</b>\n\n"
        "Discovers internships, fellowships and scholarships relevant to "
        "your profile, verifies sources, and ranks the best matches.\n\n"
        "Commands:\n"
        "/opportunities — all opportunities\n"
        "/internships — internships only\n"
        "/fellowships — fellowships &amp; scholarships\n"
        "/top — highest match scores\n"
        "/urgent — closing deadlines\n"
        "/saved — your saved list\n"
        "/stats — bot health &amp; counts\n"
        "/profile — your profile\n"
        "/update — update your profile\n"
        "/reset_profile — reset profile to defaults\n"
        "/help — this help\n\n"
        "All discovered opportunities are stored permanently and every list "
        "command returns the full set — nothing previously collected is ever "
        "hidden. Opportunity cards include Save / Details / Apply buttons."
    )


def set_usage_text():
    return (
        "✏️ <b>Profile editing</b>\n\n"
        "Usage: /set &lt;field&gt; &lt;value&gt;\n\n"
        "Fields:\n"
        "• university — /set university IIT Bombay\n"
        "• branch — /set branch Computer Science\n"
        "• degree — /set degree B.Tech\n"
        "• current_year — /set current_year 1\n"
        "• graduation_year — /set graduation_year 2029\n"
        "• country — /set country India\n"
        "• skills — /set skills C, C++, Python, SQL\n"
        "• interests — /set interests ML, Quant, Algorithms\n\n"
        "/reset_profile — restore defaults from config/profile.json"
    )


def help_text():
    return start_text()


def profile_to_text(profile):
    lines = ["🧑‍🎓 <b>Your Profile</b>"]
    lines.append(f"Country: {esc(profile.get('country'))}")
    lines.append(f"Degree: {esc(profile.get('degree'))} (Year {esc(profile.get('current_year'))})")
    lines.append(f"University: {esc(profile.get('university'))}")
    lines.append(f"Branch: {esc(profile.get('branch'))}")
    lines.append(f"Graduation year: {esc(profile.get('graduation_year'))}")
    lines.append("")
    lines.append(f"🛠 Skills: {_list(profile.get('skills'))}")
    lines.append(f"🎯 Interests: {_list(profile.get('interests'))}")
    preferred = profile.get("preferred") or {}
    allowed = _list(profile.get("allow"))
    pref_tags = [k.replace("_", " ") for k, v in preferred.items() if v]
    lines.append(f"💼 Preferred: {', '.join(pref_tags) if pref_tags else MISSING}")
    lines.append(f"✅ Allowed: {allowed}")
    return "\n".join(lines)


def empty_state(kind=None):
    label = {"internship": "internships", "fellowship": "fellowships & scholarships"}.get(kind, "opportunities")
    return "📭 No {0} found yet.".format(label)


def opportunity_to_text(opp):
    """Full card: only fields that are actually known are shown."""
    title = esc(opp.get("title")) or "Untitled"
    org = esc(opp.get("organization"))
    lines = [f"<b>{title}</b>"]
    if org:
        lines.append(org)
    facts = []
    score = _score_text(opp.get("match_score"))
    if score:
        facts.append(f"Score: {score}")
    elig = opp.get("eligibility_status")
    if elig in ELIGIBILITY_LABEL:
        facts.append(ELIGIBILITY_LABEL[elig])
    if facts:
        lines.append(" · ".join(facts))
    funding = opp.get("funding") or opp.get("stipend")
    if funding:
        lines.append(f"Stipend: {esc(funding)}")
    deadline = opp.get("deadline")
    if deadline:
        lines.append(f"Deadline: {esc(deadline)}")
    else:
        listed = format_listed(opp.get("listed_at"))
        if listed:
            lines.append(f"Listed: {esc(listed)}")
    location = opp.get("location")
    if opp.get("remote") and location:
        location = f"{location} (remote)"
    if location:
        lines.append(f"Location: {esc(location)}")
    url = opp.get("application_url") or opp.get("official_url") or opp.get("source_url")
    if url:
        lines.append(f"🔗 <a href=\"{esc(url)}\">Apply</a>")
    return "\n".join(lines)


def opportunities_to_text(items, limit=None, offset=0, total=None):
    """Compact one-line-per-item list for /opportunities etc.

    All stored items are returned when limit is None. With a limit/offset the
    caller can paginate; a header shows the running total so nothing collected
    earlier is ever hidden.
    """
    items = list(items)
    total = len(items) if total is None else total
    chunk = items[offset:offset + limit] if limit else items[offset:]
    if not chunk:
        return empty_state()
    blocks = []
    for item in chunk:
        title = esc(item.get("title")) or "Untitled"
        org = esc(item.get("organization"))
        score = _score_text(item.get("match_score"))
        emoji = priority_emoji(item.get("match_score"))
        line = f"{emoji} <b>{title}</b>"
        if org:
            line += f" — {org}"
        parts = []
        if score:
            parts.append(score)
        deadline = item.get("deadline")
        if deadline:
            parts.append(f"until {esc(deadline)[:10]}")
        else:
            listed = format_listed(item.get("listed_at"))
            if listed:
                parts.append(f"listed {esc(listed)}")
        status = item.get("status")
        if status == "expired":
            parts.append("⏳ expired")
        elif status == "closed":
            parts.append("archived")
        if parts:
            line += " · " + " · ".join(parts)
        blocks.append(line)
    if offset or limit:
        header = f"<b>Showing {offset + 1}–{offset + len(chunk)} of {total}</b>"
        blocks.insert(0, header)
    return "\n".join(blocks)


def stats_text(stats):
    counts = stats.get("counts") or {}
    last = stats.get("last_pipeline")
    lines = ["📊 <b>Bot stats</b>"]
    lines.append(f"Opportunities: {counts.get('opportunities', 0)} "
                 f"(verified {counts.get('verified', 0)}, "
                 f"saved {counts.get('saved', 0)})")
    lines.append(f"Duplicates hidden: {counts.get('duplicates', 0)}")
    lines.append(f"Sources: {counts.get('sources', 0)}")
    lines.append(f"Notifications sent: {counts.get('notifications', 0)}")
    lines.append(f"AI assessments: {counts.get('ai_assessments', 0)}")
    if last and last.get("started_at"):
        lines.append("")
        lines.append(f"Last pipeline: {last['started_at'][:16]}")
        if last.get("message"):
            try:
                import json
                summary = json.loads(last["message"])
                lines.append(f"  fellowships: {summary.get('fellowship_scout')}, "
                             f"internships: {summary.get('internship_scout')}, "
                             f"notifications: {summary.get('notifications')}, "
                             f"AI: {summary.get('ai_assessments')}")
            except (ValueError, TypeError):
                pass
    return "\n".join(lines)


def deadline_days_left(deadline_str, today=None):
    today = today or datetime.now().date()
    try:
        deadline = datetime.fromisoformat(str(deadline_str).strip()).date()
    except (ValueError, TypeError):
        return None
    return (deadline - today).days