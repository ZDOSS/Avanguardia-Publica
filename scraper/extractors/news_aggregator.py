"""
news_aggregator.py

Multi-tier news ingestion system with circuit-breaker failover.
Provider priority (production):
  1. Currents API        (account quota; local run cap)
  2. NewsData.io         (account credits; requires attribution)
  3. TheNewsAPI          (account quota; explicit production approval required)
  4. GDELT URL discovery (unmetered open-data fallback)

NewsAPI.org is ONLY used in development/local environments (not production). We store
provider-supplied headlines plus source URLs/attribution, never descriptions or scraped
article bodies.
"""

import os
import io
import zipfile
import time
import logging
import re
from urllib.parse import urlparse

import requests

from source_health import SourceHealthTracker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory request accounting (reset with the scraper process).  These are local
# safety caps, not assertions about the account's upstream plan.  Provider-returned
# quota headers are recorded separately so ETL_SUMMARY_JSON can distinguish the two.
# ---------------------------------------------------------------------------
_counters: dict[str, int] = {
    "currents": 0,
    "newsdata": 0,
    "thenewsapi": 0,
    "newsapi": 0,
}
_suppressed_counters: dict[str, int] = {
    provider: 0 for provider in _counters
}

RATE_LIMITS: dict[str, int] = {
    "currents":   1000,
    "newsdata":    200,
    "thenewsapi":  100,
    "newsapi":     100,  # dev only
}

_breaker_reasons: dict[str, str | None] = {
    provider: None for provider in RATE_LIMITS
}
_quota_observations: dict[str, dict[str, int | None]] = {
    provider: {
        "upstream_limit": None,
        "upstream_remaining": None,
        "upstream_reset": None,
        "retry_after_seconds": None,
    }
    for provider in RATE_LIMITS
}

_QUOTA_HEADER_NAMES = {
    "upstream_limit": (
        "x-ratelimit-limit",
        "x-rate-limit-limit",
        "ratelimit-limit",
        "x-ratelimit-requests-limit",
    ),
    "upstream_remaining": (
        "x-ratelimit-remaining",
        "x-rate-limit-remaining",
        "ratelimit-remaining",
        "x-ratelimit-requests-remaining",
    ),
    "upstream_reset": (
        "x-ratelimit-reset",
        "x-rate-limit-reset",
        "ratelimit-reset",
        "x-ratelimit-requests-reset",
    ),
    "retry_after_seconds": ("retry-after",),
}

# Shared request timeout
_TIMEOUT = 10


def _within_limit(provider: str) -> bool:
    return _effective_breaker_reason(provider) is None


def _bump(provider: str) -> None:
    _counters[provider] += 1


def _trip_provider_breaker(provider: str, reason: str) -> None:
    if _breaker_reasons[provider] is None:
        _breaker_reasons[provider] = reason or "circuit_breaker"


def _effective_breaker_reason(provider: str) -> str | None:
    if _breaker_reasons[provider] is not None:
        return _breaker_reasons[provider]
    if _quota_observations[provider]["upstream_remaining"] == 0:
        return "upstream_quota_exhausted"
    if _counters[provider] >= RATE_LIMITS[provider]:
        return "local_request_cap_reached"
    return None


def _record_provider_skip(
    provider: str,
    label: str,
    health: SourceHealthTracker | None,
) -> None:
    reason = _effective_breaker_reason(provider) or "provider_unavailable"
    first_suppressed_request = _suppressed_counters[provider] == 0
    _suppressed_counters[provider] += 1
    if first_suppressed_request:
        logger.warning("[%s] Provider unavailable (%s), skipping.", label, reason)
    if health:
        health.record_skip(reason)


def _nonnegative_header_integer(value) -> int | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not re.fullmatch(r"[0-9]+", normalized):
        return None
    return int(normalized)


def _observe_quota_headers(provider: str, response) -> None:
    """Retain only numeric, whitelisted quota headers from one response."""

    headers = getattr(response, "headers", None) or {}
    normalized_headers = {
        str(name).strip().lower().replace("_", "-"): value
        for name, value in headers.items()
    }
    observation = _quota_observations[provider]
    for field, candidates in _QUOTA_HEADER_NAMES.items():
        for name in candidates:
            parsed = _nonnegative_header_integer(normalized_headers.get(name))
            if parsed is not None:
                observation[field] = parsed
                break


def reset_provider_status() -> None:
    """Reset per-process request, breaker, and quota observations."""

    for provider in RATE_LIMITS:
        _counters[provider] = 0
        _suppressed_counters[provider] = 0
        _breaker_reasons[provider] = None
        for field in _quota_observations[provider]:
            _quota_observations[provider][field] = None


def get_provider_status() -> dict[str, dict]:
    status = {}
    for provider, local_cap in RATE_LIMITS.items():
        breaker_reason = _effective_breaker_reason(provider)
        upstream_remaining = _quota_observations[provider]["upstream_remaining"]
        status[provider] = {
            "requests": _counters[provider],
            "requests_suppressed": _suppressed_counters[provider],
            "request_demand": _counters[provider] + _suppressed_counters[provider],
            "local_request_cap": local_cap,
            "local_requests_remaining": max(0, local_cap - _counters[provider]),
            "breaker_tripped": breaker_reason is not None,
            "breaker_reason": breaker_reason,
            "quota_exhausted": (
                breaker_reason
                in {
                    "http_429",
                    "local_request_cap_reached",
                    "upstream_quota_exhausted",
                }
                or upstream_remaining == 0
            ),
            **_quota_observations[provider],
        }
    return status


# ---------------------------------------------------------------------------
# 1. Currents API (primary production source)
# ---------------------------------------------------------------------------
def _fetch_currents(
    full_name: str, health: SourceHealthTracker | None = None
) -> list[dict]:
    api_key = os.environ.get("CURRENTS_API_KEY")
    if not api_key:
        return []
    if not _within_limit("currents"):
        _record_provider_skip("currents", "Currents", health)
        return []

    url = "https://api.currentsapi.services/v1/search"
    params = {
        "keywords": full_name,
        "language": "en",
        "apiKey": api_key,
    }
    if health:
        health.record_attempt()
    started_at = time.monotonic()
    try:
        _bump("currents")
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        _observe_quota_headers("currents", resp)
        if not resp.ok:
            reason = f"http_{resp.status_code}"
            logger.warning("[Currents] HTTP %s — rotating to next provider.", resp.status_code)
            if health:
                health.record_failure(
                    reason, time.monotonic() - started_at
                )
                health.trip_breaker(reason)
            _trip_provider_breaker("currents", reason)
            return []
        articles = resp.json().get("news", [])
        if health:
            health.record_success(time.monotonic() - started_at)
        results = []
        for a in articles[:10]:
            title = (a.get("title") or "").strip()
            if not title or not a.get("url"):
                continue
            results.append({
                "content_summary": title[:300],
                "url": a.get("url"),
                "sentiment_score": None,
                "ingestion_method": "currents_api",
                "source": a.get("author") or "Currents API",
                "source_api": "Currents",
            })
        return results
    except Exception as exc:
        logger.error("[Currents] Error for %s: %s", full_name, exc)
        reason = "timeout" if isinstance(exc, requests.Timeout) else "request_error"
        if health:
            health.record_failure(reason, time.monotonic() - started_at)
            health.trip_breaker(reason)
        _trip_provider_breaker("currents", reason)
        return []


# ---------------------------------------------------------------------------
# 2. NewsAPI.org (DEVELOPMENT / localhost only)
# ---------------------------------------------------------------------------
def _fetch_newsapi(
    full_name: str, health: SourceHealthTracker | None = None
) -> list[dict]:
    env = os.environ.get("APP_ENV", "production").lower()
    is_dev = env in ("development", "dev", "local", "localhost")
    if not is_dev:
        return []

    api_key = os.environ.get("NEWSAPI_KEY")
    if not api_key:
        return []
    if not _within_limit("newsapi"):
        _record_provider_skip("newsapi", "NewsAPI", health)
        return []

    url = "https://newsapi.org/v2/everything"
    params = {
        "q": f'"{full_name}"',
        "language": "en",
        "pageSize": 10,
        "apiKey": api_key,
    }
    if health:
        health.record_attempt()
    started_at = time.monotonic()
    try:
        _bump("newsapi")
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        _observe_quota_headers("newsapi", resp)
        if not resp.ok:
            reason = f"http_{resp.status_code}"
            logger.warning("[NewsAPI] HTTP %s — rotating.", resp.status_code)
            if health:
                health.record_failure(
                    reason, time.monotonic() - started_at
                )
                health.trip_breaker(reason)
            _trip_provider_breaker("newsapi", reason)
            return []
        articles = resp.json().get("articles", [])
        if health:
            health.record_success(time.monotonic() - started_at)
        results = []
        for a in articles:
            title = (a.get("title") or "").strip()
            if not title or not a.get("url"):
                continue
            results.append({
                "content_summary": title[:300],
                "url": a.get("url"),
                "sentiment_score": None,
                "ingestion_method": "newsapi_dev",
                "source": (a.get("source") or {}).get("name", "NewsAPI"),
                "source_api": "NewsAPI (development)",
            })
        return results
    except Exception as exc:
        logger.error("[NewsAPI] Error for %s: %s", full_name, exc)
        reason = "timeout" if isinstance(exc, requests.Timeout) else "request_error"
        if health:
            health.record_failure(reason, time.monotonic() - started_at)
            health.trip_breaker(reason)
        _trip_provider_breaker("newsapi", reason)
        return []


# ---------------------------------------------------------------------------
# 3. NewsData.io (fallback / analytical tier)
#    Free tier requires attribution: "Data powered by NewsData.io"
# ---------------------------------------------------------------------------
def _fetch_newsdata(
    full_name: str, health: SourceHealthTracker | None = None
) -> list[dict]:
    api_key = os.environ.get("NEWSDATA_API_KEY")
    if not api_key:
        return []
    if not _within_limit("newsdata"):
        _record_provider_skip("newsdata", "NewsData", health)
        return []

    url = "https://newsdata.io/api/1/news"
    params = {
        "q": full_name,
        "language": "en",
        "apikey": api_key,
    }
    if health:
        health.record_attempt()
    started_at = time.monotonic()
    try:
        _bump("newsdata")
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        _observe_quota_headers("newsdata", resp)
        if not resp.ok:
            reason = f"http_{resp.status_code}"
            logger.warning("[NewsData] HTTP %s — rotating.", resp.status_code)
            if health:
                health.record_failure(
                    reason, time.monotonic() - started_at
                )
                health.trip_breaker(reason)
            _trip_provider_breaker("newsdata", reason)
            return []
        articles = resp.json().get("results", [])
        if health:
            health.record_success(time.monotonic() - started_at)
        results = []
        for a in articles[:10]:
            # Map NewsData's sentiment field
            raw_sentiment = a.get("sentiment")
            sentiment_score: float | None = None
            if isinstance(raw_sentiment, (int, float)):
                sentiment_score = float(raw_sentiment)
            elif isinstance(raw_sentiment, str):
                mapping = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
                sentiment_score = mapping.get(raw_sentiment.lower())

            title = (a.get("title") or "").strip()
            if not title or not a.get("link"):
                continue
            results.append({
                "content_summary": title[:240]
                + "\nData powered by NewsData.io: https://newsdata.io/",
                "url": a.get("link"),
                "sentiment_score": sentiment_score,
                "ingestion_method": "newsdata_api",
                "source": a.get("source_id", "NewsData.io"),
                "source_api": "NewsData.io",
            })
        return results
    except Exception as exc:
        logger.error("[NewsData] Error for %s: %s", full_name, exc)
        reason = "timeout" if isinstance(exc, requests.Timeout) else "request_error"
        if health:
            health.record_failure(reason, time.monotonic() - started_at)
            health.trip_breaker(reason)
        _trip_provider_breaker("newsdata", reason)
        return []


# ---------------------------------------------------------------------------
# 4. TheNewsAPI (secondary fallback)
# ---------------------------------------------------------------------------
def _thenewsapi_allowed() -> bool:
    env = os.environ.get("APP_ENV", "production").lower()
    if env in ("development", "dev", "local", "localhost", "test"):
        return True
    return os.environ.get("THENEWSAPI_PRODUCTION_APPROVED", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _fetch_thenewsapi(
    full_name: str, health: SourceHealthTracker | None = None
) -> list[dict]:
    api_key = os.environ.get("THENEWSAPI_KEY")
    if not api_key:
        return []
    if not _thenewsapi_allowed():
        if health:
            health.record_skip("production_terms_not_approved")
        return []
    if not _within_limit("thenewsapi"):
        _record_provider_skip("thenewsapi", "TheNewsAPI", health)
        return []

    url = "https://api.thenewsapi.com/v1/news/all"
    params = {
        "search": full_name,
        "language": "en",
        "limit": 10,
        "api_token": api_key,
    }
    if health:
        health.record_attempt()
    started_at = time.monotonic()
    try:
        _bump("thenewsapi")
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        _observe_quota_headers("thenewsapi", resp)
        if not resp.ok:
            reason = f"http_{resp.status_code}"
            logger.warning("[TheNewsAPI] HTTP %s — rotating.", resp.status_code)
            if health:
                health.record_failure(
                    reason, time.monotonic() - started_at
                )
                health.trip_breaker(reason)
            _trip_provider_breaker("thenewsapi", reason)
            return []
        articles = resp.json().get("data", [])
        if health:
            health.record_success(time.monotonic() - started_at)
        results = []
        for a in articles:
            title = (a.get("title") or "").strip()
            if not title or not a.get("url"):
                continue
            results.append({
                "content_summary": title[:300],
                "url": a.get("url"),
                "sentiment_score": None,
                "ingestion_method": "thenewsapi",
                "source": a.get("source", "TheNewsAPI"),
                "source_api": "TheNewsAPI",
            })
        return results
    except Exception as exc:
        logger.error("[TheNewsAPI] Error for %s: %s", full_name, exc)
        reason = "timeout" if isinstance(exc, requests.Timeout) else "request_error"
        if health:
            health.record_failure(reason, time.monotonic() - started_at)
            health.trip_breaker(reason)
        _trip_provider_breaker("thenewsapi", reason)
        return []


# ---------------------------------------------------------------------------
# 5. GDELT URL discovery (unmetered open-data fallback)
# ---------------------------------------------------------------------------
_GDELT_PROJECT_HOST = "data.gdeltproject.org"
_GDELT_STORAGE_BASE = "https://storage.googleapis.com/data.gdeltproject.org"
GDELT_MASTER_URL = f"{_GDELT_STORAGE_BASE}/gdeltv2/lastupdate.txt"
_GDELT_GKG_PATH_RE = re.compile(r"/gdeltv2/[0-9]{14}\.gkg\.csv\.zip")

# In-memory cache to prevent re-downloading the TSV for every politician
_gdelt_cache: list[tuple[str, str]] | None = None
_gdelt_cache_url: str | None = None
_gdelt_cache_time: float | None = None
_GDELT_CACHE_TTL = 900  # 15 minutes


def _gdelt_storage_url(manifest_url: str) -> str | None:
    """Map an exact GDELT GKG object to its certificate-valid storage URL."""

    parsed = urlparse(manifest_url)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.netloc.lower() != _GDELT_PROJECT_HOST
        or parsed.params
        or parsed.query
        or parsed.fragment
        or not _GDELT_GKG_PATH_RE.fullmatch(parsed.path)
    ):
        return None
    return f"{_GDELT_STORAGE_BASE}{parsed.path}"


def _get_gdelt_cache() -> list[tuple[str, str]] | None:
    global _gdelt_cache, _gdelt_cache_url, _gdelt_cache_time
    
    # Short-circuit BEFORE the manifest network request if the cache is still fresh
    if _gdelt_cache is not None and _gdelt_cache_time is not None:
        if time.monotonic() - _gdelt_cache_time < _GDELT_CACHE_TTL:
            return _gdelt_cache

    try:
        # Step 1: get the latest file manifest
        resp = requests.get(GDELT_MASTER_URL, timeout=_TIMEOUT)
        resp.raise_for_status()
        # The file lists three lines: CSV, mentions, GKG
        lines = resp.text.strip().splitlines()
        # Find the line that corresponds to the GKG zip
        gkg_url = None
        for line in lines:
            if line.endswith(".gkg.csv.zip"):
                gkg_url = _gdelt_storage_url(line.split()[-1])
                break
        
        if not gkg_url:
            logger.warning("[GDELT] Could not locate GKG zip in manifest.")
            return None

        # If we already downloaded this exact file in this run, return the cache
        if _gdelt_cache is not None and _gdelt_cache_url == gkg_url:
            _gdelt_cache_time = time.monotonic()
            return _gdelt_cache

        # Step 2: download the GKG file (it's a zipped TSV)
        gkg_resp = requests.get(gkg_url, timeout=30)
        gkg_resp.raise_for_status()

        new_cache = []
        with zipfile.ZipFile(io.BytesIO(gkg_resp.content)) as z:
            # GKG zip files contain exactly one file
            filename = z.namelist()[0]
            with z.open(filename) as f:
                for raw_line in f:
                    try:
                        line = raw_line.decode("utf-8", errors="replace")
                        cols = line.split("\t")
                        # GKG column 4 is the source document URL
                        if len(cols) > 11:
                            src_url = cols[4].strip()
                            # column 11 contains person entities in V2 GKG, not column 10 (which is locations)
                            entities_col = cols[11].strip().lower()
                            if src_url:
                                new_cache.append((src_url, entities_col))
                    except Exception:
                        continue

        _gdelt_cache = new_cache
        _gdelt_cache_url = gkg_url
        _gdelt_cache_time = time.monotonic()
        return _gdelt_cache
    except Exception as exc:
        logger.error("[GDELT] Error fetching master file: %s", exc)
        return None


def _fetch_gdelt_urls(full_name: str, max_articles: int = 10) -> list[str] | None:
    """
    Filters the cached GDELT GKG dataset for rows matching the politician's name.
    """
    cache = _get_gdelt_cache()
    if cache is None:
        return None
    name_lower = full_name.lower()
    urls: list[str] = []

    for src_url, entities_col in cache:
        if len(urls) >= max_articles:
            break
        # Match using the full name to avoid common last name false positives
        if name_lower and name_lower in entities_col:
            urls.append(src_url)

    return list(dict.fromkeys(urls))


def _fetch_gdelt(
    full_name: str, health: SourceHealthTracker | None = None
) -> list[dict]:
    """Use GDELT only to discover source URLs; never republish article body text."""
    if health and health.breaker_tripped:
        health.record_skip("breaker_open")
        return []
    if health:
        health.record_attempt()
    started_at = time.monotonic()
    urls = _fetch_gdelt_urls(full_name)
    if urls is None:
        if health:
            health.record_failure("gdelt_feed_unavailable", time.monotonic() - started_at)
        return []
    if health:
        health.record_success(time.monotonic() - started_at)

    attribution = "Media URL indexed by the GDELT Project: https://www.gdeltproject.org/"
    return [
        {
            "content_summary": attribution,
            "url": url,
            "sentiment_score": None,
            "ingestion_method": "gdelt_gkg_url_discovery",
            "source": "GDELT Project",
            "source_api": "GDELT",
        }
        for url in urls
    ]


# ---------------------------------------------------------------------------
# Public interface: circuit-breaker manager
# ---------------------------------------------------------------------------
def get_news_data(
    full_name: str,
    health: SourceHealthTracker | None = None,
    provider_health: dict[str, SourceHealthTracker] | None = None,
) -> list[dict]:
    """
    Attempts each news provider in priority order, returning results from the
    first provider that succeeds. Falls back to GDELT if all API quotas are
    exhausted or no keys are configured.

    Returns a list of dicts compatible with loader.process_mentions().
    """
    provider_health = provider_health or {}
    if health and health.breaker_tripped:
        health.record_skip("breaker_open")
        return []
    if health:
        health.record_attempt()

    # --- Development-only NewsAPI first (no-op in production) ---
    dev_results = _fetch_newsapi(full_name, health=provider_health.get("newsapi"))
    if dev_results:
        logger.info("[NewsAggregator] Served by NewsAPI (dev) for %s", full_name)
        if health:
            health.record_success()
        return dev_results

    # --- Tier 1: Currents API ---
    currents_tracker = provider_health.get("currents")
    if os.environ.get("CURRENTS_API_KEY"):
        if _within_limit("currents"):
            results = _fetch_currents(full_name, health=currents_tracker)
        else:
            _record_provider_skip("currents", "Currents", currents_tracker)
            results = None
        if results is not None and _breaker_reasons["currents"] is None:
            if results:
                logger.info("[NewsAggregator] Served by Currents for %s", full_name)
            if health:
                health.record_success()
            return results

    # --- Tier 2: NewsData.io ---
    newsdata_tracker = provider_health.get("newsdata")
    if os.environ.get("NEWSDATA_API_KEY"):
        if _within_limit("newsdata"):
            results = _fetch_newsdata(full_name, health=newsdata_tracker)
        else:
            _record_provider_skip("newsdata", "NewsData", newsdata_tracker)
            results = None
        if results is not None and _breaker_reasons["newsdata"] is None:
            if results:
                logger.info("[NewsAggregator] Served by NewsData for %s", full_name)
            if health:
                health.record_success()
            return results

    # --- Tier 3: TheNewsAPI ---
    thenewsapi_tracker = provider_health.get("thenewsapi")
    if os.environ.get("THENEWSAPI_KEY") and _thenewsapi_allowed():
        if _within_limit("thenewsapi"):
            results = _fetch_thenewsapi(full_name, health=thenewsapi_tracker)
        else:
            _record_provider_skip("thenewsapi", "TheNewsAPI", thenewsapi_tracker)
            results = None
        if results is not None and _breaker_reasons["thenewsapi"] is None:
            if results:
                logger.info("[NewsAggregator] Served by TheNewsAPI for %s", full_name)
            if health:
                health.record_success()
            return results
    elif os.environ.get("THENEWSAPI_KEY") and not _thenewsapi_allowed():
        if thenewsapi_tracker:
            thenewsapi_tracker.record_skip("production_terms_not_approved")

    # --- Tier 4: GDELT URL discovery (always available, no key needed) ---
    logger.info("[NewsAggregator] Falling back to GDELT pipeline for %s", full_name)
    gdelt_tracker = provider_health.get("gdelt")
    failures_before = gdelt_tracker.failures if gdelt_tracker else 0
    results = _fetch_gdelt(full_name, health=gdelt_tracker)
    if health:
        if gdelt_tracker and (
            gdelt_tracker.failures > failures_before or gdelt_tracker.breaker_tripped
        ):
            health.record_failure("all_news_providers_unavailable")
        else:
            health.record_success()
    return results
