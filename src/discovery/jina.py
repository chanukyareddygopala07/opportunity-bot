"""Jina Reader bridge — renders JavaScript pages as clean text/markdown.

Unlocks sources that static fetching cannot read (SPA listing pages) and
powers detail-page enrichment for accuracy checks. Every call is
rate-limited and size-capped; failures degrade to None so callers decide.
"""
import json
import logging
import time
import urllib.request

logger = logging.getLogger(__name__)

READER_URL = "https://r.jina.ai/"
USER_AGENT = "aawara-opportunity-radar/1.0"
DEFAULT_TIMEOUT = 30
MAX_BYTES = 1_500_000

_last_call = 0.0
MIN_INTERVAL = 2.0  # be polite to the free tier


def read(url, timeout=DEFAULT_TIMEOUT):
    """Read a URL through Jina Reader. Returns markdown text or None."""
    global _last_call
    wait = MIN_INTERVAL - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()

    req = urllib.request.Request(
        READER_URL + url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/plain",
            # Structured mode returns title/url/content JSON; plain is fine
            # for our parsers and smaller over the wire.
            "X-Return-Format": "markdown",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(MAX_BYTES)
    except Exception as exc:
        logger.info("jina read failed for %s: %s", url, exc)
        return None
    text = data.decode("utf-8", "replace")
    # Jina prefixes bot-blocked targets with a warning; surface it so
    # callers can treat content as unreliable instead of parsing garbage.
    if "Warning: Target URL returned error" in text[:400]:
        logger.info("jina reports target error for %s", url)
        return None
    return text


def read_json(url, timeout=DEFAULT_TIMEOUT):
    """Read a URL through Jina and parse its content field as JSON."""
    text = read(url, timeout=timeout)
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None
