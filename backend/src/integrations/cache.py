"""Cache service with Protocol pattern for dependency injection.

Provides RedisCacheService (real cache) and NullCacheService (no-op fallback).
"""

import json
from typing import Protocol

import redis

from ..config import settings


class CacheService(Protocol):
    """Cache service interface."""

    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str, ttl: int) -> None: ...
    def get_json(self, key: str) -> dict | None: ...
    def set_json(self, key: str, data: dict, ttl: int) -> None: ...


class RedisCacheService:
    """Redis-backed cache implementation."""

    def __init__(self, redis_url: str) -> None:
        self._client = redis.from_url(redis_url, decode_responses=True)
        self._client.ping()

    def get(self, key: str) -> str | None:
        try:
            return self._client.get(key)
        except Exception:
            return None

    def set(self, key: str, value: str, ttl: int) -> None:
        try:
            self._client.setex(key, ttl, value)
        except Exception:
            pass

    def get_json(self, key: str) -> dict | None:
        raw = self.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def set_json(self, key: str, data: dict, ttl: int) -> None:
        self.set(key, json.dumps(data, ensure_ascii=False), ttl)


class NullCacheService:
    """No-op cache for when Redis is unavailable."""

    def get(self, key: str) -> str | None:
        return None

    def set(self, key: str, value: str, ttl: int) -> None:
        pass

    def get_json(self, key: str) -> dict | None:
        return None

    def set_json(self, key: str, data: dict, ttl: int) -> None:
        pass


def create_cache_service() -> CacheService:
    """Factory: create the appropriate cache service based on configuration."""
    if not settings.redis_url:
        return NullCacheService()
    try:
        return RedisCacheService(settings.redis_url)
    except Exception:
        return NullCacheService()
