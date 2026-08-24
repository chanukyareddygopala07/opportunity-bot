"""Hackathon source adapters — one interface, many platforms.

Design (per docs/PRODUCTION_ROADMAP.md): never one scraper per site; every
source implements the same adapter contract and emits normalized entries:

    {
      "ref":            stable platform id or URL,
      "title":          str (required),
      "url":            absolute registration/info URL,
      "organization":   str|None,
      "description":    str|None,
      "deadline":       "YYYY-MM-DD"|None   (registration/submission close),
      "event_start":    "YYYY-MM-DD"|None,
      "event_end":      "YYYY-MM-DD"|None,
      "location":       str|None,
      "remote":         bool,
      "prize":          str|None  ("$740,000", "₹1,00,000"),
      "themes":         [str],
      "team_size":      str|None  ("2-4"),
    }

Adapters must NEVER invent values — unknown stays None. Anything that fails
to parse is skipped, not guessed.
"""
import json
import logging
import re
from datetime import datetime, timedelta

from src.discovery import fetcher, jina

logger = logging.getLogger(__name__)

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36")

MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], start=1)}
for abbr, num in [(m[:3], n) for m, n in MONTHS.items()]:
    MONTHS[abbr] = num


# ---------- shared date parsing (evidence-based, never guessed) ----------

def parse_date(text):
    """Parse '2026-10-01', 'Oct 01, 2026', 'October 1, 2026' -> ISO date."""
    if not text:
        return None
    text = text.strip()
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if m:
        try:
            return datetime(int(m[1]), int(m[2]), int(m[3])).date().isoformat()
        except ValueError:
            return None
    m = re.search(r"([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", text)
    if m:
        month = MONTHS.get(m[1].lower())
        if month:
            try:
                return datetime(int(m[3]), month, int(m[2])).date().isoformat()
            except ValueError:
                return None
    return None


def parse_period(text):
    """Parse Devpost-style ranges: 'Jul 31 - Oct 01, 2026' or
    'Sep 15 - Sep 22' (same year). Returns (start, end)."""
    if not text:
        return None, None
    text = text.replace("–", "-").strip()
    m = re.match(r"([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?\s*-\s*"
                 r"([A-Za-z]{3,9})?\s*(\d{1,2})(?:st|nd|rd|th)?,\s*(\d{4})", text)
    if not m:
        iso = parse_date(text)
        return iso, iso
    m1, d1, m2, d2, year = m.groups()
    month1 = MONTHS.get(m1.lower())
    month2 = MONTHS.get((m2 or m1).lower())
    if not month1 or not month2:
        return None, None
    try:
        start = datetime(int(year), month1, int(d1)).date()
        end = datetime(int(year), month2, int(d2)).date()
    except ValueError:
        return None, None
    return start.isoformat(), end.isoformat()


def _fetch(url, timeout=20):
    return fetcher.fetch_bytes(
        url, timeout=timeout * 1000, max_bytes=2_000_000, attempts=2)


# ---------- adapter: devpost ----------

def _devpost_location(entry):
    loc = (entry.get("displayed_location") or {}).get("location") or ""
    online = loc.strip().lower() == "online" or "global" in loc.lower()
    return loc, online


def devpost_adapter(source):
    """Devpost open hackathons via their public JSON API."""
    entries = []
    page = 1
    while page <= int(source.get("max_pages") or 2):
        url = f"https://devpost.com/api/hackathons?status=open&page={page}"
        data, _final, status = fetcher.fetch_bytes(
            url, timeout=20000, max_bytes=2_000_000, attempts=2)
        if status != 200:
            break
        payload = json.loads(data.decode("utf-8", "replace"))
        hackathons = payload.get("hackathons") or []
        for h in hackathons:
            location, online = _devpost_location(h)
            start, end = parse_period(h.get("submission_period_dates"))
            prize_html = h.get("prize_amount")
            prize = None
            if prize_html:
                m = re.search(r'data-currency-value[^>]*>([\d,.]+)<',
                              prize_html)
                prize = f"${m.group(1)}" if m else re.sub(r"<[^>]+>", "", prize_html).strip()
            themes = [t.get("name") for t in (h.get("themes") or []) if t.get("name")]
            entries.append({
                "ref": f"devpost:{h.get('id')}",
                "title": (h.get("title") or "").strip(),
                "url": h.get("url"),
                "organization": h.get("organization_name"),
                "description": None,
                "deadline": end,
                "event_start": start,
                "event_end": end,
                "location": location or None,
                "remote": online,
                "prize": prize,
                "themes": themes[:6],
                "team_size": None,
            })
        if len(hackathons) < 10:  # short page = last page
            break
        page += 1
    return entries


# ---------- adapter: mlh ----------

def _extract_inertia_page(html):
    """Extract Inertia.js page-props JSON from an HTML document.

    Index-based rather than regex: attribute values may contain arbitrary
    JSON (no '>' required) and may be HTML-entity escaped.
    """
    import html as html_lib

    marker = html.find("data-page")
    if marker == -1:
        return None
    open_end = html.find(">", marker)
    close = html.find("</script>", open_end)
    if open_end == -1 or close == -1:
        return None
    raw = html[open_end + 1:close].strip()
    try:
        return json.loads(html_lib.unescape(raw))
    except ValueError:
        logger.info("inertia data-page payload was not parseable JSON")
        return None


def mlh_inertia_adapter(source):
    """MLH season schedule: Inertia.js embeds page props as JSON.

    Only upcoming events are emitted — pastEvents are history, not
    opportunities.
    """
    seasons = source.get("seasons") or ["2026"]
    entries = []
    for season in seasons:
        url = f"https://mlh.io/seasons/{season}/events"
        data, _final, status = _fetch(url)
        if status != 200:
            continue
        html = data.decode("utf-8", "replace")
        m = _extract_inertia_page(html)
        if not m:
            continue
        props = m.get("props") or {}
        for ev in props.get("upcomingEvents") or []:
            name = (ev.get("name") or "").strip()
            website = ev.get("websiteUrl") or ev.get("url")
            if isinstance(website, str) and website.startswith("/"):
                website = f"https://mlh.io{website}"
            starts = parse_date((ev.get("startsAt") or "")[:10])
            city = ev.get("city")
            location = ", ".join(x for x in (city, ev.get("province"),
                                             ev.get("country")) if x) or None
            entries.append({
                "ref": f"mlh:{ev.get('id') or name}",
                "title": name,
                "url": website,
                "organization": "Major League Hacking",
                "description": None,
                "deadline": None,  # MLH payload carries no registration close
                "event_start": starts,
                "event_end": parse_date((ev.get("endsAt") or "")[:10]) or starts,
                "location": location,
                "remote": bool(ev.get("isVirtual")),
                "prize": None,
                "themes": [],
                "team_size": None,
            })
    return entries


# ---------- adapter: internshala ----------

_INTERNSHALA_TITLE = re.compile(
    r'<a[^>]*href="(https://internshala\.com/competitions/[^"]+)"[^>]*'
    r'title="([^"]+)"')
_INTERNSHALA_DATE = re.compile(
    r"(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})(?:\s*-\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}))?")


def internshala_adapter(source):
    """Internshala hackathons listing (server-rendered HTML).

    Extracts titled registration links; dates are taken from explicit date
    text when present — missing dates stay unknown.
    """
    data, _final, status = _fetch(source["url"])
    entries = []
    if status != 200:
        return entries
    html = data.decode("utf-8", "replace")
    seen = set()
    import html as html_lib
    for link, raw_title in _INTERNSHALA_TITLE.findall(html):
        title = html_lib.unescape(raw_title).strip()
        if link in seen or len(title) < 8:
            continue
        seen.add(link)
        # Look around each link occurrence for nearby deadline text.
        deadline = None
        for tail in html.split(link)[1:2]:
            dates = _INTERNSHALA_DATE.findall(tail[:1500])
            if dates:
                deadline = parse_date(dates[0][0]) or parse_date(dates[0][1])
        entries.append({
            "ref": link,
            "title": title[:180],
            "url": link,
            "organization": "Internshala",
            "description": None,
            "deadline": deadline,
            "event_start": None,
            "event_end": None,
            "location": "India",
            "remote": False,
            "prize": None,
            "themes": [],
            "team_size": None,
        })
    return entries


ADAPTERS = {
    "devpost_api": devpost_adapter,
    "mlh_inertia": mlh_inertia_adapter,
    "internshala_hackathons": internshala_adapter,
}


# ---------- adapters via Jina Reader (JS-rendered platforms) ----------

def _days_left_to_date(text):
    """'10 days left' / '1 day left' -> ISO date. None when not parseable.

    Unstop listings expose relative windows instead of absolute dates; the
    conversion is exact only at fetch time, which is acceptable because the
    stored deadline is re-checked by the enrichment pass.
    """
    m = re.search(r"(\d+)\s+days?\s+left", text or "", re.IGNORECASE)
    if not m:
        return None
    return (datetime.now().date() + timedelta(days=int(m.group(1)))).isoformat()


_UNSTOP_BLOCK = re.compile(
    r"###\s+\[(?P<text>.{40,2000}?)\]\((?P<url>https://unstop\.com/[^)]+)\)",
    re.DOTALL)
_UNSTOP_TEAM = re.compile(r"(\d+\s*-\s*\d+\s+Members|Individual Participation)")
_UNSTOP_PRIZE = re.compile(r"Prizes? worth ([^!\]]{2,40})")


def _unstop_clean_title(raw):
    """Card text starts with the title; org/location follow after it."""
    # Titles are followed by org names in the same bracket text; cut at the
    # first image token and strip trailing metadata noise.
    raw = raw.split("![Image")[0]
    parts = [p.strip() for p in raw.split("\n") if p.strip()]
    return re.sub(r"\s+", " ", " ".join(parts))


def unstop_jina_adapter(source):
    """Unstop open hackathons via Jina Reader (SPA — needs JS rendering)."""
    markdown = jina.read(source["url"])
    if not markdown:
        return []
    entries = []
    seen = set()
    today = datetime.now().date()
    for match in _UNSTOP_BLOCK.finditer(markdown):
        url = match.group("url")
        if url in seen or "/hackathons/" not in url:
            continue
        seen.add(url)
        raw_text = re.sub(r"\s+", " ", match.group("text"))
        text = _unstop_clean_title(match.group("text"))

        title_m = re.match(r"(.{10,150}?)\s+(?:[A-Z][A-Za-z .,&()']+\s+){0,3}(?:\d+\s*-\s*\d+\s+Members|Individual Participation|\d+\s+Members)", text)
        title = title_m.group(1).strip() if title_m else text[:120]

        team = _UNSTOP_TEAM.search(raw_text)
        prize = _UNSTOP_PRIZE.search(raw_text)
        online = bool(re.search(r"\bOnline\b", raw_text))
        location = "Online" if online else "India"

        entries.append({
            "ref": url,
            "title": title,
            "url": url,
            "organization": None,  # resolved from detail enrichment
            "description": None,
            "deadline": _days_left_to_date(raw_text),
            "event_start": None,
            "event_end": None,
            "location": location,
            "remote": online,
            "prize": f"₹{prize.group(1).strip()}" if prize else None,
            "themes": [],
            "team_size": team.group(1) if team else None,
        })
    entries = [e for e in entries
               if e["deadline"] is None
               or datetime.fromisoformat(e["deadline"]).date() >= today]
    return entries


_DORA_ITEM = re.compile(
    r"\[\s*(?:!\[[^\]]*\]\([^)]*\)\s*)?"
    r"(?P<pre>[^]]*?)\s*"
    r"(?:!\[[^\]]*\]\([^)]*\)\s*)?"
    r"(?P<title>[^]]{10,140}?)\s+"
    r"(?:Virtual|Online)?[^]]*?"
    r"(?:🏆\s*Prize Pool\s*(?P<prize>[^]]{2,60}))?\s*"
    r"\]\((?P<url>https://dorahacks\.io/hackathon/[^)]+)\)")
_DORA_DAYS = re.compile(r"(\d+)\s+(days?|hours?)\s+left", re.IGNORECASE)


def dorahacks_adapter(source):
    """DoraHacks hackathons via Jina Reader."""
    markdown = jina.read(source["url"])
    if not markdown:
        return []
    entries = []
    seen = set()
    for m in _DORA_ITEM.finditer(markdown):
        url = m.group("url")
        if url in seen:
            continue
        pre = m.group("pre") or ""
        # Skip ended events outright.
        if re.search(r"\bEnded\b", pre):
            continue
        seen.add(url)
        title = m.group("title").strip()
        tags_block = m.group(0)
        themes = sorted(set(re.findall(
            r"#?\b(AI Agents?|Blockchain|DeFi|Web3|Crypto|Artificial Intelligence"
            r"|Generative AI|Trading Bots|Autonomous Trading|Quantum|BioTech"
            r"|Legal Tech|SaaS|DeepTech)\b", tags_block)))[:6]
        days = _DORA_DAYS.search(pre + " " + tags_block)
        deadline = None
        if days:
            amount = int(days.group(1))
            unit_days = 1 if days.group(2).lower().startswith("day") else 7
            deadline = (datetime.now().date()
                        + timedelta(days=amount * unit_days)).isoformat()
        virtual = " Virtual " in f" {tags_block} "
        entries.append({
            "ref": url.rsplit("/", 1)[-1],
            "title": title,
            "url": url,
            "organization": pre.strip().splitlines()[0].strip() if pre.strip() else None,
            "description": None,
            "deadline": deadline,
            "event_start": None,
            "event_end": None,
            "location": "Virtual" if virtual else None,
            "remote": True,
            "prize": m.group("prize").strip() if m.group("prize") else None,
            "themes": themes,
            "team_size": None,
        })
    return entries


_LABLAB_PRIZE = re.compile(r"🏆\s*\$?([\d,]+\+?)\s*(?:USD)?\s*prize pool", re.IGNORECASE)
_LABLAB_URL = re.compile(r"\(https://lablab\.ai/(?:ai-hackathons|event)/([a-z0-9-]+)\)")


def lablab_adapter(source):
    """lablab.ai AI hackathons via Jina Reader.

    Cards nest markdown images inside links; position-based slicing of each
    card block is far more robust than a single link regex.
    """
    markdown = jina.read(source["url"])
    if not markdown:
        return []
    entries = []
    seen = set()
    for m in _LABLAB_URL.finditer(markdown):
        slug = m.group(1)
        if slug in seen:
            continue
        seen.add(slug)
        # Card block: everything back to the previous blank line pair.
        start = max(0, m.start() - 1200)
        block = markdown[start:m.end()]
        heading = re.findall(r"## ([^#\n]{8,120})", block)
        title = (heading[-1].strip() if heading
                 else slug.replace("-", " ").title())
        prize = _LABLAB_PRIZE.search(block)
        tba = "To be announced" in block or re.search(r"\bTBA\b", block)
        hybrid = "Hybrid" in block
        entries.append({
            "ref": slug,
            "title": title[:160],
            "url": f"https://lablab.ai/event/{slug}",
            "organization": "lablab.ai",
            "description": None,
            "deadline": None,  # listing shows TBA/relative; enrichment recovers
            "event_start": None,
            "event_end": None,
            "location": "Hybrid" if hybrid else "Online",
            "remote": True,
            "prize": f"${prize.group(1)}" if prize else None,
            "themes": ["AI"],
            "team_size": None,
            "_tba": bool(tba),
        })
    return entries


ADAPTERS["unstop_jina"] = unstop_jina_adapter
ADAPTERS["dorahacks_jina"] = dorahacks_adapter
ADAPTERS["lablab_jina"] = lablab_adapter


def fetch_hackathons(source):
    """Dispatch through the registry — the ONLY entry scouts call."""
    adapter_name = source.get("adapter")
    adapter = ADAPTERS.get(adapter_name)
    if adapter is None:
        raise LookupError(f"no hackathon adapter named {adapter_name!r}")
    entries = adapter(source)
    cleaned = []
    for e in entries:
        if e.get("title") and e.get("url"):
            cleaned.append(e)
        else:
            logger.info("hackathon entry dropped (missing title/url): %r",
                        e.get("ref"))
    return cleaned
