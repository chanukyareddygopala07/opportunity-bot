"""Phase 7 — ATS adapters: official public job-board APIs (no auth, no scraping).

Greenhouse: boards-api.greenhouse.io/v1/boards/{org}/jobs
Ashby:      api.ashbyhq.com/posting-api/job-board/{org}
"""
import json
from html.parser import HTMLParser

from src.discovery import fetcher

ATS_MAX_BYTES = 12 * 1024 * 1024


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def strip_html(html_text):
    if not html_text:
        return None
    parser = _TextExtractor()
    parser.feed(html_text)
    return " ".join(" ".join(parser.parts).split())


def parse_greenhouse(data):
    entries = []
    for job in data.get("jobs", []):
        location = job.get("location") or {}
        if isinstance(location, dict):
            location = location.get("name")
        departments = ", ".join(
            d.get("name") or "" for d in job.get("departments") or []
        ) or None
        entries.append({
            "id": job.get("id"),
            "title": job.get("title"),
            "url": job.get("absolute_url"),
            "description": strip_html(job.get("content")),
            "location": location,
            "remote": bool(job.get("remote")),
            "published": job.get("updated_at"),
            "department": departments,
        })
    return [entry for entry in entries if entry["title"] and entry["url"]]


def parse_ashby(data):
    entries = []
    for job in data.get("jobs", []):
        if job.get("isListed") is False:
            continue
        workplace = job.get("workplaceType") or ""
        entries.append({
            "id": job.get("id"),
            "title": job.get("title"),
            "url": job.get("applyUrl") or job.get("jobUrl"),
            "description": job.get("descriptionPlain"),
            "location": job.get("location"),
            "remote": bool(job.get("isRemote")) or workplace.lower() == "remote",
            "hybrid": workplace.lower() == "hybrid",
            "published": job.get("publishedAt"),
            "department": job.get("department"),
            "employment_type": job.get("employmentType"),
        })
    return [entry for entry in entries if entry["title"] and entry["url"]]


def parse_amazon(data):
    entries = []
    for job in data.get("jobs", []):
        location = job.get("location") or ""
        if job.get("country_code") == "IN":
            location = f"India, {location}"
        entries.append({
            "id": job.get("id"),
            "title": job.get("title"),
            "url": job.get("url_next_step") or job.get("url_application"),
            "description": job.get("description_short") or job.get("description"),
            "location": location,
            "remote": "remote" in location.lower() or "anywhere" in location.lower(),
            "published": job.get("posted_date"),
            "department": job.get("team"),
            "employment_type": "internship" if job.get("is_intern") else None,
        })
    return [entry for entry in entries if entry["title"] and entry["url"]]


def parse_lever(data):
    """Lever public postings API: https://api.lever.co/v0/postings/{site}?mode=json
    Returns a JSON array of postings (text, categories, hostedUrl, descriptionPlain)."""
    entries = []
    for job in data if isinstance(data, list) else []:
        categories = job.get("categories") or {}
        location = categories.get("location") or categories.get("allLocations") or ""
        if isinstance(location, list):
            location = ", ".join(str(x) for x in location)
        entries.append({
            "id": job.get("id"),
            "title": job.get("text"),
            "url": job.get("hostedUrl"),
            "description": job.get("descriptionPlain") or job.get("descriptionBodyPlain"),
            "location": location,
            "remote": "remote" in str(location).lower() or "anywhere" in str(location).lower(),
            "published": job.get("createdAt"),
            "department": categories.get("team") or categories.get("department"),
            "employment_type": categories.get("commitment"),
        })
    return [entry for entry in entries if entry["title"] and entry["url"]]


def _fetch_json(url, max_bytes=ATS_MAX_BYTES, source=None):
    data, _final, status = fetcher.fetch_bytes(url, max_bytes=max_bytes, source=source)
    return json.loads(data.decode("utf-8", errors="replace")), status


def _dig(data, path):
    """Resolve a dotted key path like 'content.hits.total'."""
    node = data
    for part in str(path).split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _paginated_json(source, url, page_key="offset", page_size_key="result_limit",
                   total_key="total_jobs", jobs_key="jobs", start_page=0):
    """Generic offset/cursor pagination for JSON APIs.

    Offset-style pagination (Amazon: offset=0,100,200… with result_limit)
    advances the offset by the page size; page-style APIs (offset=1,2,3…)
    advance by one. Iterates until: no more items, total reached, a short
    (partial) page, max pages reached, or max results reached. total_key may
    be a dotted path (e.g. "content.hits.total").
    """
    import os
    max_pages = int(source.get("max_pages") or 10)
    max_results = int(os.environ.get("MAX_RESULTS_PER_SOURCE", 1000))
    limit = int(source.get("result_limit") or 100)
    results = []
    page = start_page
    step = limit if page_key == "offset" else 1
    pages_fetched = 0
    while True:
        sep = "&" if "?" in url else "?"
        page_url = f"{url}{sep}{page_key}={page}&{page_size_key}={limit}"
        data, status = _fetch_json(page_url, source=source)
        jobs = data.get(jobs_key) or []
        results.extend(jobs)
        pages_fetched += 1
        total = _dig(data, total_key)
        if not jobs or len(jobs) < limit:
            break
        if total and len(results) >= total:
            break
        if len(results) >= max_results:
            break
        page += step
        if pages_fetched >= max_pages:
            break
    return results


def fetch_ats(source, method):
    url = source["url"]
    if method == "ats_greenhouse":
        data, _status = _fetch_json(url, source=source)
        return parse_greenhouse(data)
    if method == "ats_ashby":
        data, _status = _fetch_json(url, source=source)
        return parse_ashby(data)
    if method == "ats_json":
        raw_jobs = _paginated_json(source, url, page_key="offset",
                                   page_size_key="result_limit",
                                   total_key="content.hits.total", jobs_key="jobs")
        return parse_amazon({"jobs": raw_jobs})
    if method == "ats_lever":
        data, _status = _fetch_json(url, source=source)
        return parse_lever(data)
    raise ValueError(f"unsupported ATS method: {method}")


ATS_FETCHERS = {
    "ats_greenhouse": fetch_ats,
    "ats_ashby": fetch_ats,
    "ats_json": fetch_ats,
    "ats_lever": fetch_ats,
}