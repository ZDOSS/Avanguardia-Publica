"""
news_aggregator.py

Multi-tier news ingestion system with circuit-breaker failover.
Provider priority (production):
  1. Currents API        (~1,000 req/day free)
  2. NewsData.io         (~200 req/day free — requires attribution)
  3. TheNewsAPI          (~100 req/day free)
  4. GDELT + newspaper3k (unmetered open-source fallback)

NewsAPI.org is ONLY used in development/local environments (not production).
"""

import os
import csv
import io
import zipfile
import time
import logging
import requests
from datetime import datetime, timezone

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


# ---------------------------------------------------------------------------
# 1. Currents API (primary production source)
# ---------------------------------------------------------------------------
def _fetch_currents(full_name: str) -> list[dict]:
    api_key = os.environ.get("CURRENTS_API_KEY")
    if not api_key:
        return []
    if not _within_limit("currents"):
        logger.warning("[Currents] Daily request limit reached, skipping.")
        return []

    url = "https://api.currentsapi.services/v1/search"
    params = {
        "keywords": full_name,
        "language": "en",
        "apiKey": api_key,
    }
    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        _bump("currents")
        if resp.status_code == 429:
            logger.warning("[Currents] 429 Too Many Requests — rotating to next provider.")
            _counters["currents"] = RATE_LIMITS["currents"]  # trip the breaker
            return []
        resp.raise_for_status()
        articles = resp.json().get("news", [])
        results = []
        for a in articles[:10]:
            results.append({
                "content_summary": (a.get("title", "") + " — " + a.get("description", ""))[:300],
                "url": a.get("url"),
                "sentiment_score": None,
                "ingestion_method": "currents_api",
                "source": a.get("author") or "Currents API",
            })
        return results
    except Exception as exc:
        logger.error("[Currents] Error for %s: %s", full_name, exc)
        return []


# ---------------------------------------------------------------------------
# 2. NewsAPI.org (DEVELOPMENT / localhost only)
# ---------------------------------------------------------------------------
def _fetch_newsapi(full_name: str) -> list[dict]:
    env = os.environ.get("APP_ENV", "production").lower()
    is_dev = env in ("development", "dev", "local", "localhost")
    if not is_dev:
        return []

    api_key = os.environ.get("NEWSAPI_KEY")
    if not api_key:
        return []
    if not _within_limit("newsapi"):
        logger.warning("[NewsAPI] Daily request limit reached, skipping.")
        return []

    url = "https://newsapi.org/v2/everything"
    params = {
        "q": f'"{full_name}"',
        "language": "en",
        "pageSize": 10,
        "apiKey": api_key,
    }
    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        _bump("newsapi")
        if resp.status_code == 429:
            _counters["newsapi"] = RATE_LIMITS["newsapi"]
            logger.warning("[NewsAPI] 429 — rate limit tripped.")
            return []
        resp.raise_for_status()
        articles = resp.json().get("articles", [])
        results = []
        for a in articles:
            results.append({
                "content_summary": (a.get("title", "") + " — " + (a.get("description") or ""))[:300],
                "url": a.get("url"),
                "sentiment_score": None,
                "ingestion_method": "newsapi_dev",
                "source": (a.get("source") or {}).get("name", "NewsAPI"),
            })
        return results
    except Exception as exc:
        logger.error("[NewsAPI] Error for %s: %s", full_name, exc)
        return []


# ---------------------------------------------------------------------------
# 3. NewsData.io (fallback / analytical tier)
#    Free tier requires attribution: "Data powered by NewsData.io"
# ---------------------------------------------------------------------------
def _fetch_newsdata(full_name: str) -> list[dict]:
    api_key = os.environ.get("NEWSDATA_API_KEY")
    if not api_key:
        return []
    if not _within_limit("newsdata"):
        logger.warning("[NewsData] Daily request limit reached, skipping.")
        return []

    url = "https://newsdata.io/api/1/news"
    params = {
        "q": full_name,
        "language": "en",
        "apikey": api_key,
    }
    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        _bump("newsdata")
        if resp.status_code == 429:
            _counters["newsdata"] = RATE_LIMITS["newsdata"]
            logger.warning("[NewsData] 429 — rate limit tripped.")
            return []
        resp.raise_for_status()
        articles = resp.json().get("results", [])
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

            results.append({
                "content_summary": (
                    (a.get("title") or "") + " — " + (a.get("description") or "")
                )[:300]
                + "\n[Data powered by NewsData.io]",  # attribution required by free tier TOS
                "url": a.get("link"),
                "sentiment_score": sentiment_score,
                "ingestion_method": "newsdata_api",
                "source": a.get("source_id", "NewsData.io"),
            })
        return results
    except Exception as exc:
        logger.error("[NewsData] Error for %s: %s", full_name, exc)
        return []


# ---------------------------------------------------------------------------
# 4. TheNewsAPI (secondary fallback)
# ---------------------------------------------------------------------------
def _fetch_thenewsapi(full_name: str) -> list[dict]:
    api_key = os.environ.get("THENEWSAPI_KEY")
    if not api_key:
        return []
    if not _within_limit("thenewsapi"):
        logger.warning("[TheNewsAPI] Daily request limit reached, skipping.")
        return []

    url = "https://api.thenewsapi.com/v1/news/all"
    params = {
        "search": full_name,
        "language": "en",
        "limit": 10,
        "api_token": api_key,
    }
    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        _bump("thenewsapi")
        if resp.status_code == 429:
            _counters["thenewsapi"] = RATE_LIMITS["thenewsapi"]
            logger.warning("[TheNewsAPI] 429 — rate limit tripped.")
            return []
        resp.raise_for_status()
        articles = resp.json().get("data", [])
        results = []
        for a in articles:
            results.append({
                "content_summary": (a.get("title", "") + " — " + (a.get("description") or ""))[:300],
                "url": a.get("url"),
                "sentiment_score": None,
                "ingestion_method": "thenewsapi",
                "source": a.get("source", "TheNewsAPI"),
            })
        return results
    except Exception as exc:
        logger.error("[TheNewsAPI] Error for %s: %s", full_name, exc)
        return []


# ---------------------------------------------------------------------------
# 5. GDELT + newspaper3k (unmetered open-source fallback)
# ---------------------------------------------------------------------------
GDELT_MASTER_URL = (
    "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"
)

# In-memory cache to prevent re-downloading the TSV for every politician
_gdelt_cache: list[tuple[str, str]] | None = None
_gdelt_cache_url: str | None = None
_gdelt_cache_time: float | None = None
_GDELT_CACHE_TTL = 900  # 15 minutes

def _get_gdelt_cache() -> list[tuple[str, str]]:
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
        # First line is the main event CSV; we want the GKG (third line)
        gkg_line = lines[2] if len(lines) >= 3 else lines[0]
        gkg_url = gkg_line.split()[-1]  # last token is the URL

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
                        if len(cols) > 4:
                            src_url = cols[4].strip()
                            # column 10 contains person entities (rough keyword match)
                            entities_col = cols[10].strip().lower() if len(cols) > 10 else ""
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
        return []


def _fetch_gdelt_urls(full_name: str, max_articles: int = 10) -> list[str]:
    """
    Filters the cached GDELT GKG dataset for rows matching the politician's name.
    """
    cache = _get_gdelt_cache()
    name_lower = full_name.lower()
    urls: list[str] = []

    for src_url, entities_col in cache:
        if len(urls) >= max_articles:
            break
        # Match using the full name to avoid common last name false positives
        if name_lower and name_lower in entities_col:
            urls.append(src_url)

    return urls


def _scrape_article_text(url: str) -> str | None:
    """
    Downloads and extracts clean article text from a URL using newspaper3k.
    Falls back to a raw truncated HTTP response if newspaper3k is unavailable.
    """
    try:
        from newspaper import Article  # type: ignore
        article = Article(url)
        article.download()
        article.parse()
        return article.text[:400] if article.text else None
    except ImportError:
        # newspaper3k not installed — fall back to raw HEAD+snippet
        try:
            r = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
            # Return first 300 chars of visible text (very rough)
            return r.text[:300].strip() or None
        except Exception:
            return None
    except Exception as exc:
        logger.warning("[newspaper3k] Could not parse %s: %s", url, exc)
        return None


def _fetch_gdelt(full_name: str) -> list[dict]:
    """Full GDELT pipeline: fetch URLs then scrape article text."""
    urls = _fetch_gdelt_urls(full_name)
    results = []
    for url in urls:
        text = _scrape_article_text(url)
        if text:
            results.append({
                "content_summary": text[:300],
                "url": url,
                "sentiment_score": None,
                "ingestion_method": "gdelt_scraper",
                "source": "GDELT",
            })
        time.sleep(0.5)  # polite delay between scrape requests
    return results


# ---------------------------------------------------------------------------
# Public interface: circuit-breaker manager
# ---------------------------------------------------------------------------
def get_news_data(full_name: str) -> list[dict]:
    """
    Attempts each news provider in priority order, returning results from the
    first provider that succeeds. Falls back to GDELT if all API quotas are
    exhausted or no keys are configured.

    Returns a list of dicts compatible with loader.process_mentions().
    """
    # --- Development-only NewsAPI first (no-op in production) ---
    dev_results = _fetch_newsapi(full_name)
    if dev_results:
        logger.info("[NewsAggregator] Served by NewsAPI (dev) for %s", full_name)
        return dev_results

    # --- Tier 1: Currents API ---
    if _within_limit("currents") and os.environ.get("CURRENTS_API_KEY"):
        results = _fetch_currents(full_name)
        if results:
            logger.info("[NewsAggregator] Served by Currents for %s", full_name)
            return results

    # --- Tier 2: NewsData.io ---
    if _within_limit("newsdata") and os.environ.get("NEWSDATA_API_KEY"):
        results = _fetch_newsdata(full_name)
        if results:
            logger.info("[NewsAggregator] Served by NewsData for %s", full_name)
            return results

    # --- Tier 3: TheNewsAPI ---
    if _within_limit("thenewsapi") and os.environ.get("THENEWSAPI_KEY"):
        results = _fetch_thenewsapi(full_name)
        if results:
            logger.info("[NewsAggregator] Served by TheNewsAPI for %s", full_name)
            return results

    # --- Tier 4: GDELT + newspaper3k (always available, no key needed) ---
    logger.info("[NewsAggregator] Falling back to GDELT pipeline for %s", full_name)
    return _fetch_gdelt(full_name)
