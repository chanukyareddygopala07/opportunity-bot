"""Phase 6 — polite HTTP fetcher: timeout, retries, exponential backoff,
per-domain delay, HTTP status handling, source cooldown. Never aggressive,
never bypasses protections.

Phase 18: env-configurable limits (REQUEST_TIMEOUT_MS, MAX_RETRIES,
PER_DOMAIN_DELAY_MS, DISCOVERY_CONCURRENCY) and per-source rate limits.
"""
import logging
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15
MAX_ATTEMPTS = 3
MAX_BYTES = 12 * 1024 * 1024
MIN_DELAY_SECONDS = 2.0
USER_AGENT = "OpportunityBot/0.2 (personal student project; respectful crawler; contact local operator)"

RETRYABLE_5XX = (500, 502, 503, 504)
MAX_COOLDOWN_SECONDS = 3600 * 6


class FetchError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def env_bool(name, default=False):
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "y") or default


def get_limits():
    return {
        "timeout": env_int("REQUEST_TIMEOUT_MS", DEFAULT_TIMEOUT * 1000) / 1000.0,
        "attempts": env_int("MAX_RETRIES", MAX_ATTEMPTS) + 1,
        "per_domain_delay": env_int("PER_DOMAIN_DELAY_MS", int(MIN_DELAY_SECONDS * 1000)) / 1000.0,
    }


_last_request = {}
_failure_streak = {}


def _backoff_delay(attempt, status_code=None):
    if status_code == 429:
        return 30.0
    return 2 ** attempt


def _cooldown_for(status_code):
    if status_code == 429:
        return 1800
    if status_code == 403:
        return 3600
    if status_code in RETRYABLE_5XX:
        return 300
    return 900


def _request(url, timeout, max_bytes, attempts, per_domain_delay, source=None):
    parsed = urlparse(url)
    domain = parsed.netloc
    delay = max(per_domain_delay, (source or {}).get("rate_limit_ms", 0) / 1000.0)
    elapsed = time.monotonic() - _last_request.get(domain, 0)
    wait = delay - elapsed
    if wait > 0:
        time.sleep(wait)

    if source and source.get("id") is not None:
        from src import sources as registry
        cooldown = registry.cooldown_remaining(source["id"]) if hasattr(registry, "cooldown_remaining") else 0
        if cooldown:
            raise FetchError(f"source in cooldown ({cooldown}s remaining)", code=429)

    attempt = 0
    while True:
        attempt += 1
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = response.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise FetchError(f"response larger than {max_bytes} bytes: {url}")
                _last_request[domain] = time.monotonic()
                _failure_streak.pop(domain, None)
                return data, response.geturl(), response.status
        except urllib.error.HTTPError as exc:
            code = exc.code
            retry = code in RETRYABLE_5XX or code == 429
            if code == 404 or code == 403 or code == 401:
                retry = False
            if retry and attempt < attempts:
                delay = _backoff_delay(attempt, code)
                logger.warning("fetch attempt %d/%d for %s got HTTP %d; retrying in %ss",
                               attempt, attempts, url, code, delay)
                time.sleep(delay)
                continue
            streak = _failure_streak.get(domain, 0) + 1
            _failure_streak[domain] = streak
            raise FetchError(f"HTTP Error {code}: {exc.reason}", code=code) from exc
        except FetchError:
            raise
        except Exception as exc:
            if attempt >= attempts:
                raise FetchError(f"failed after {attempts} attempts: {exc}") from exc
            delay = _backoff_delay(attempt)
            logger.warning("fetch attempt %d/%d failed for %s (%s); retrying in %ss",
                           attempt, attempts, url, exc, delay)
            time.sleep(delay)
    raise FetchError(f"unreachable")



def fetch_bytes(url, timeout=None, max_bytes=MAX_BYTES, attempts=None, source=None):
    limits = get_limits()
    timeout = timeout or limits["timeout"]
    attempts = attempts or limits["attempts"]
    data, final_url, status = _request(
        url, timeout, max_bytes, attempts, limits["per_domain_delay"], source
    )
    return data, final_url, status


def fetch(url, timeout=None, max_bytes=MAX_BYTES, attempts=None, source=None):
    data, final_url, status = fetch_bytes(
        url, timeout=timeout, max_bytes=max_bytes, attempts=attempts, source=source
    )
    return data.decode("utf-8", errors="replace"), final_url, status


def fetch_json(url, timeout=None, max_bytes=MAX_BYTES, attempts=None, source=None):
    import json
    text, final_url, status = fetch(url, timeout=timeout, max_bytes=max_bytes,
                                   attempts=attempts, source=source)
    return json.loads(text), final_url, status