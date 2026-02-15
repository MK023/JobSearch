"""Tests for cache service."""

from src.integrations.cache import NullCacheService


class TestNullCacheService:
    def test_get_returns_none(self):
        cache = NullCacheService()
        assert cache.get("any_key") is None

    def test_set_does_nothing(self):
        cache = NullCacheService()
        cache.set("key", "value", 60)  # Should not raise

    def test_get_json_returns_none(self):
        cache = NullCacheService()
        assert cache.get_json("any_key") is None

    def test_set_json_does_nothing(self):
        cache = NullCacheService()
        cache.set_json("key", {"data": "test"}, 60)  # Should not raise
