"""
news_aggregator.py

Multi-tier news ingestion system with circuit-breaker failover.
Provider priority (production):
  1. Currents API        (~1,000 req/day free)
  2. NewsData.io         (~200 req/day free — requires attribution)
  3. TheNewsAPI          (~100 req/day free; explicit production approval required)
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
import requests

from source_health import SourceHealthTracker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory rate-limit counters (reset on each scraper run)
# For a persistent counter across runs, swap these dicts for a Redis/file cache.
# ---------------------------------------------------------------------------
_counters: dict[str, int] = {
    "currents": 0,
    "newsdata": 0,
    "thenewsapi": 0,
    "newsapi": 0,
}

RATE_LIMITS: dict[str, int] = {
    "currents":   1000,
    "newsdata":    200,
    "thenewsapi":  100,
    "newsapi":     100,  # dev only
}

# Shared request timeout
_TIMEOUT = 10


def _within_limit(provider: str) -> bool:
    return _counters[provider] < RATE_LIMITS[provider]


def _bump(provider: str) -> None:
    _counters[provider] += 1


def get_provider_status() -> dict[str, dict]:
    return {
        provider: {
            "requests": _counters[provider],
            "limit": limit,
            "breaker_tripped": _counters[provider] >= limit,
        }
        for provider, limit in RATE_LIMITS.items()
    }


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
        logger.warning("[Currents] Daily request limit reached, skipping.")
        if health:
            health.record_skip("request_budget_exhausted")
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
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        _bump("currents")
        if not resp.ok:
            logger.warning("[Currents] HTTP %s — rotating to next provider.", resp.status_code)
            if health:
                health.record_failure(
                    f"http_{resp.status_code}", time.monotonic() - started_at
                )
                health.trip_breaker(f"http_{resp.status_code}")
            _counters["currents"] = RATE_LIMITS["currents"]  # trip the breaker
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
        if health:
            reason = "timeout" if isinstance(exc, requests.Timeout) else "request_error"
            health.record_failure(reason, time.monotonic() - started_at)
            health.trip_breaker(reason)
        _counters["currents"] = RATE_LIMITS["currents"]  # trip the breaker
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
        logger.warning("[NewsAPI] Daily request limit reached, skipping.")
        if health:
            health.record_skip("request_budget_exhausted")
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
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        _bump("newsapi")
        if not resp.ok:
            logger.warning("[NewsAPI] HTTP %s — rotating.", resp.status_code)
            if health:
                health.record_failure(
                    f"http_{resp.status_code}", time.monotonic() - started_at
                )
                health.trip_breaker(f"http_{resp.status_code}")
            _counters["newsapi"] = RATE_LIMITS["newsapi"]
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
        if health:
            reason = "timeout" if isinstance(exc, requests.Timeout) else "request_error"
            health.record_failure(reason, time.monotonic() - started_at)
            health.trip_breaker(reason)
        _counters["newsapi"] = RATE_LIMITS["newsapi"]
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
        logger.warning("[NewsData] Daily request limit reached, skipping.")
        if health:
            health.record_skip("request_budget_exhausted")
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
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        _bump("newsdata")
        if not resp.ok:
            logger.warning("[NewsData] HTTP %s — rotating.", resp.status_code)
            if health:
                health.record_failure(
                    f"http_{resp.status_code}", time.monotonic() - started_at
                )
                health.trip_breaker(f"http_{resp.status_code}")
            _counters["newsdata"] = RATE_LIMITS["newsdata"]
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
        if health:
            reason = "timeout" if isinstance(exc, requests.Timeout) else "request_error"
            health.record_failure(reason, time.monotonic() - started_at)
            health.trip_breaker(reason)
        _counters["newsdata"] = RATE_LIMITS["newsdata"]
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
        logger.warning("[TheNewsAPI] Daily request limit reached, skipping.")
        if health:
            health.record_skip("request_budget_exhausted")
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
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        _bump("thenewsapi")
        if not resp.ok:
            logger.warning("[TheNewsAPI] HTTP %s — rotating.", resp.status_code)
            if health:
                health.record_failure(
                    f"http_{resp.status_code}", time.monotonic() - started_at
                )
                health.trip_breaker(f"http_{resp.status_code}")
            _counters["thenewsapi"] = RATE_LIMITS["thenewsapi"]
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
        if health:
            reason = "timeout" if isinstance(exc, requests.Timeout) else "request_error"
            health.record_failure(reason, time.monotonic() - started_at)
            health.trip_breaker(reason)
        _counters["thenewsapi"] = RATE_LIMITS["thenewsapi"]
        return []


# ---------------------------------------------------------------------------
# 5. GDELT URL discovery (unmetered open-data fallback)
# ---------------------------------------------------------------------------
GDELT_MASTER_URL = (
    "https://data.gdeltproject.org/gdeltv2/lastupdate.txt"
)

# In-memory cache to prevent re-downloading the TSV for every politician
_gdelt_cache: list[tuple[str, str]] | None = None
_gdelt_cache_url: str | None = None
_gdelt_cache_time: float | None = None
_GDELT_CACHE_TTL = 900  # 15 minutes

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
                gkg_url = line.split()[-1]
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
    if _within_limit("currents") and os.environ.get("CURRENTS_API_KEY"):
        results = _fetch_currents(full_name, health=provider_health.get("currents"))
        if _within_limit("currents"):  # if breaker didn't trip, API is healthy
            if results:
                logger.info("[NewsAggregator] Served by Currents for %s", full_name)
            if health:
                health.record_success()
            return results

    # --- Tier 2: NewsData.io ---
    if _within_limit("newsdata") and os.environ.get("NEWSDATA_API_KEY"):
        results = _fetch_newsdata(full_name, health=provider_health.get("newsdata"))
        if _within_limit("newsdata"):
            if results:
                logger.info("[NewsAggregator] Served by NewsData for %s", full_name)
            if health:
                health.record_success()
            return results

    # --- Tier 3: TheNewsAPI ---
    if (
        _within_limit("thenewsapi")
        and os.environ.get("THENEWSAPI_KEY")
        and _thenewsapi_allowed()
    ):
        results = _fetch_thenewsapi(
            full_name, health=provider_health.get("thenewsapi")
        )
        if _within_limit("thenewsapi"):
            if results:
                logger.info("[NewsAggregator] Served by TheNewsAPI for %s", full_name)
            if health:
                health.record_success()
            return results
    elif os.environ.get("THENEWSAPI_KEY") and not _thenewsapi_allowed():
        tracker = provider_health.get("thenewsapi")
        if tracker:
            tracker.record_skip("production_terms_not_approved")

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
