"""Thin Redis cache wrapper for read-heavy API endpoints.

All operations are best-effort: if Redis is unreachable, the wrapped
function executes as a normal uncached call. This matches the project's
principle of "no silent failures" — a downed cache should not return
errors to users, but it should also not block the response.
"""
import json
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any

import redis

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: redis.Redis | None = None


def get_client() -> redis.Redis | None:
    """Lazy-connect to Redis. Returns ``None`` if the connection fails."""
    global _client
    if _client is None:
        try:
            _client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            _client.ping()
        except redis.RedisError as e:
            logger.warning("Redis cache unavailable: %s", e)
            _client = None
    return _client


def cache_json(key: str | Callable[..., str], ttl_seconds: int) -> Callable:
    """Decorator: cache the JSON-serialized return value under ``key``.

    ``key`` may be a static string or a callable that receives the same
    ``*args, **kwargs`` as the wrapped function and returns a key
    string. The callable form is required for parameterised endpoints
    so that ``?page=2&state=CA`` does not collide with ``?page=1``.

    The wrapper also accepts a no-arg ``force_refresh=False`` keyword.
    When ``True``, the cache is bypassed and the function is re-executed.
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args, force_refresh: bool = False, **kwargs):
            resolved_key = key(*args, **kwargs) if callable(key) else key
            client = get_client()
            if client is not None and not force_refresh:
                try:
                    hit = client.get(resolved_key)
                    if hit is not None:
                        return json.loads(hit)
                except redis.RedisError as e:
                    logger.warning("Redis cache read failed for %s: %s", resolved_key, e)
            result = func(*args, **kwargs)
            if client is not None:
                try:
                    client.setex(resolved_key, ttl_seconds, json.dumps(result, default=str))
                except redis.RedisError as e:
                    logger.warning("Redis cache write failed for %s: %s", resolved_key, e)
            return result

        return wrapper

    return decorator


def invalidate(key: str) -> None:
    """Drop a single key. Silently no-ops when the cache is unavailable."""
    client = get_client()
    if client is None:
        return
    try:
        client.delete(key)
    except redis.RedisError as e:
        logger.warning("Redis cache invalidate failed for %s: %s", key, e)
