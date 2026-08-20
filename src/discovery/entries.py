"""Phase 8 — shared entry fetching for both scouts.

Supported source methods: rss, html_news, html_links, ats_greenhouse,
ats_ashby, pdf_links (public PDFs fetched and parsed locally).
"""
import logging
import re
from urllib.parse import urlparse

from src import db
from src.discovery import ats, fetcher, parsers
from src.extraction import extractor, pdf

logger = logging.getLogger(__name__)

ATS_METHODS = ("ats_greenhouse", "ats_ashby", "ats_json", "ats_lever")
PDF_LINK_LIMIT = 10
PDF_MAX_BYTES = 10 * 1024 * 1024
PDF_TEXT_LIMIT = 20000
DESCRIPTION_LIMIT = 1500
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_GENERIC_LABELS = {"read more", "more", "download", "download pdf", "view", "click here"}


def fetch_entries(source):
    method = source.get("method", "rss")
    if method in ATS_METHODS:
        org = source["url"].rstrip("/").split("/")[-1]
        return ats.fetch_ats(source, method)
    text, final_url, _status = fetcher.fetch(source["url"], source=source)
    if method == "rss":
        return parsers.parse_feed(text)
    if method == "html_news":
        return parsers.parse_news_html(text, final_url)
    if method == "pdf_links":
        return _fetch_pdf_entries(text, final_url, source)
    return parsers.parse_html_links(text, final_url)


def _title_from_pdf(pdf_text, url):
    for line in pdf_text.splitlines():
        line = line.strip()
        if 8 <= len(line) <= 140:
            return line
    stem = url.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return stem.replace("_", " ").replace("-", " ").strip() or "PDF notice"


def _fetch_pdf_entries(page_text, base_url, source):
    links = parsers.parse_html_links(page_text, base_url)
    base_host = urlparse(base_url).netloc
    pdf_links = [link for link in links if link["url"].lower().endswith(".pdf")]
    pdf_links.sort(key=lambda link: urlparse(link["url"]).netloc != base_host)
    entries = []
    for link in pdf_links[:PDF_LINK_LIMIT]:
        url = _CONTROL_CHARS.sub("", link["url"])
        try:
            data, _final, _status = fetcher.fetch_bytes(url, max_bytes=PDF_MAX_BYTES, source=source)
            pdf_text = pdf.extract_pdf_text(data, max_chars=PDF_TEXT_LIMIT)
            anchor_title = link["title"]
            if anchor_title and anchor_title.strip().lower() in _GENERIC_LABELS:
                anchor_title = None
            title = anchor_title or _title_from_pdf(pdf_text, url)
            entries.append({
                "title": title,
                "url": url,
                "description": pdf_text[:DESCRIPTION_LIMIT],
                "_full_text": pdf_text,
            })
        except Exception as exc:
            db.log_error(source.get("name") or base_url, type(exc).__name__, str(exc))
            logger.warning("pdf link failed: %s (%s)", url, exc)
    return entries


def enrich(opp, entry):
    """Merge Phase 8 extracted fields into an opportunity dict (never overwriting
    values the source already provided explicitly). The entry title joins the
    haystack because sources like RSS often carry the eligibility hints there."""
    haystack = " ".join(filter(None, [
        entry.get("title"),
        entry.get("_full_text") or entry.get("description"),
    ]))
    fields = extractor.extract_fields(haystack)
    for key, value in fields.items():
        if key not in opp and value not in (None, [], ""):
            opp[key] = value
    return opp