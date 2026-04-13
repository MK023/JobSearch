"""Cache service with Protocol pattern for dependency injection.

Provides RedisCacheService (real cache) and NullCacheService (no-op fallback).
"""

import json
import logging
from typing import Any, Protocol, cast

import redis

from ..config import settings

logger = logging.getLogger(__name__)


class CacheService(Protocol):
    """Cache service interface."""

    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str, ttl: int) -> None: ...
    def get_json(self, key: str) -> dict[str, Any] | None: ...
    def set_json(self, key: str, data: dict[str, Any], ttl: int) -> None: ...
    def stats(self) -> dict[str, int]: ...


class RedisCacheService:
    """Redis-backed cache implementation with hit/miss instrumentation.

    Counters live on the instance — read them via `stats()` to surface
    cache effectiveness. Redis errors are caught (so callers always get
    a safe miss) but **logged** at WARNING so they're not silent.
    """

    def __init__(self, redis_url: str) -> None:
        self._client = redis.from_url(redis_url, decode_responses=True)  # type: ignore[no-untyped-call]
        self._client.ping()
        self.hits = 0
        self.misses = 0
        self.errors = 0

    def get(self, key: str) -> str | None:
        try:
            value = cast(str | None, self._client.get(key))
        except Exception as exc:
            self.errors += 1
            logger.warning("cache get failed key=%s err=%s", key, exc)
            return None
        if value is None:
            self.misses += 1
        else:
            self.hits += 1
        return value

    def set(self, key: str, value: str, ttl: int) -> None:
        try:
            self._client.setex(key, ttl, value)
        except Exception as exc:
            self.errors += 1
            logger.warning("cache set failed key=%s err=%s", key, exc)

    def get_json(self, key: str) -> dict[str, Any] | None:
        raw = self.get(key)
        if raw is None:
            return None
        try:
            return cast(dict[str, Any], json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            logger.warning("cache poisoned key=%s — invalid JSON, treating as miss", key)
            return None

    def set_json(self, key: str, data: dict[str, Any], ttl: int) -> None:
        self.set(key, json.dumps(data, ensure_ascii=False), ttl)

    def stats(self) -> dict[str, int]:
        """Return cumulative hit/miss/error counters since process start."""
        return {"hits": self.hits, "misses": self.misses, "errors": self.errors}


class NullCacheService:
    """No-op cache for when Redis is unavailable."""

    def get(self, key: str) -> str | None:
        return None

    def set(self, key: str, value: str, ttl: int) -> None:
        pass

    def get_json(self, key: str) -> dict[str, Any] | None:
        return None

    def set_json(self, key: str, data: dict[str, Any], ttl: int) -> None:
        pass

    def stats(self) -> dict[str, int]:
        return {"hits": 0, "misses": 0, "errors": 0}


def create_cache_service() -> CacheService:
    """Factory: create the appropriate cache service based on configuration."""
    if not settings.redis_url:
        return NullCacheService()
    try:
        return RedisCacheService(settings.redis_url)
    except Exception:
        return NullCacheService()
