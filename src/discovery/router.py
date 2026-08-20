"""Crawler router — decides which crawler should fetch a source.

Decision inputs: source config (preferred crawler, method), URL shape,
robots policy. Every decision is recorded as `crawler_used` on
discovery_runs so the pipeline is auditable.

Crawler vocabulary (matches the target architecture):
    crawlee        — static HTML fetch (default)
    crawl4ai       — AI-friendly static pages (structured extraction)
    firecrawl      — complex/composite pages (self-hosted)
    playwright     — JS-heavy pages (rendered DOM)
    browser_use    — interactive flows (login, pagination)
    ats            — ATS JSON APIs (Greenhouse / Ashby / Lever)
    pdf            — PDF-based listings (pypdf extraction)
    api            — plain JSON APIs
    respect_robots — disallowed by robots.txt; must not be fetched
"""
from urllib.parse import urlparse

STATIC = "crawlee"
AI_FRIENDLY = "crawl4ai"
COMPLEX = "firecrawl"
JS_HEAVY = "playwright"
INTERACTIVE = "browser_use"
ATS = "ats"
PDF = "pdf"
API = "api"
RESPECT_ROBOTS = "respect_robots"

_ATS_DOMAINS = (
    "greenhouse.io", "boards.greenhouse.io", "jobs.lever.co", "job-boards.greenhouse.io",
    "boards-api.greenhouse.io", "api.lever.co", "jobs.ashbyhq.com",
)
_ATS_HINTS = ("/ats/", "/boards/", "greenhouse", "lever", "ashby")

# Sources that require a rendered browser are declared by their method;
# everything ATS-shaped is handled by the ATS adapter, anything else static.
_METHOD_TO_CRAWLER = {
    "ats": ATS,
    "ats_greenhouse": ATS,
    "ats_ashby": ATS,
    "ats_lever": ATS,
    "generic_json": API,
    "json": API,
    "rss": AI_FRIENDLY,
    "pdf": PDF,
    "playwright": JS_HEAVY,
    "browser_use": INTERACTIVE,
    "firecrawl": COMPLEX,
}


def _looks_like_ats(url):
    host = (urlparse(url or "").hostname or "").lower()
    if any(d in host for d in _ATS_DOMAINS):
        return True
    return any(hint in (url or "").lower() for hint in _ATS_HINTS)


def _looks_like_pdf(url):
    path = (urlparse(url or "").path or "").lower()
    return path.endswith(".pdf") or "/pdf" in path


def _looks_like_api(url):
    path = (urlparse(url or "").path or "").lower()
    return path.endswith(".json") or "/api/" in path or "/feed" in path


def select_crawler(source=None, url=None, robots_disallowed=False):
    """Choose the crawler for a source dict or raw URL."""
    url = url or (source or {}).get("url")
    if robots_disallowed:
        return RESPECT_ROBOTS
    if source and source.get("crawler"):
        return str(source["crawler"]).strip().lower()
    if source and source.get("method"):
        mapped = _METHOD_TO_CRAWLER.get(str(source["method"]).lower())
        if mapped:
            return mapped
    if _looks_like_ats(url):
        return ATS
    if _looks_like_pdf(url):
        return PDF
    if _looks_like_api(url):
        return API
    return STATIC


_PRIORITY_RANK = {"high": 3, "medium": 2, "low": 1}
_PRIORITY_LABEL = {3: "high", 2: "medium", 1: "low"}


def priority_for_source(source, recent_deadlines=None):
    """Crawl priority from config priority + nearby deadlines of live items."""
    base = _PRIORITY_RANK.get(str((source or {}).get("priority", "")).lower(), 2)
    if recent_deadlines:
        for d in recent_deadlines:
            if d is not None and 0 <= d <= 7:
                return "high"
            if d is not None and d <= 30 and base < 3:
                return _PRIORITY_LABEL[base + 1]
    return _PRIORITY_LABEL[base]