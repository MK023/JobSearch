"""Tests for cache service."""

from unittest.mock import MagicMock

from src.integrations.cache import NullCacheService, RedisCacheService


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

    def test_stats_returns_zeros(self):
        cache = NullCacheService()
        assert cache.stats() == {"hits": 0, "misses": 0, "errors": 0}


class TestRedisCacheStats:
    def _make_cache(self, mock_client):
        """Build a RedisCacheService with a mocked redis client (no real connection)."""
        cache = RedisCacheService.__new__(RedisCacheService)
        cache._client = mock_client
        cache.hits = 0
        cache.misses = 0
        cache.errors = 0
        return cache

    def test_hit_increments_hits(self):
        client = MagicMock()
        client.get.return_value = "hello"
        cache = self._make_cache(client)
        assert cache.get("k") == "hello"
        assert cache.stats() == {"hits": 1, "misses": 0, "errors": 0}

    def test_miss_increments_misses(self):
        client = MagicMock()
        client.get.return_value = None
        cache = self._make_cache(client)
        assert cache.get("k") is None
        assert cache.stats() == {"hits": 0, "misses": 1, "errors": 0}

    def test_get_exception_increments_errors_and_returns_none(self):
        client = MagicMock()
        client.get.side_effect = RuntimeError("boom")
        cache = self._make_cache(client)
        assert cache.get("k") is None
        assert cache.stats() == {"hits": 0, "misses": 0, "errors": 1}

    def test_set_exception_increments_errors(self):
        client = MagicMock()
        client.setex.side_effect = RuntimeError("boom")
        cache = self._make_cache(client)
        cache.set("k", "v", 60)
        assert cache.stats() == {"hits": 0, "misses": 0, "errors": 1}

    def test_get_json_poisoned_value_treated_as_miss(self):
        client = MagicMock()
        client.get.return_value = "{not valid json"
        cache = self._make_cache(client)
        assert cache.get_json("k") is None
        # The underlying get() recorded a hit (it returned a string), then
        # parse failed — counter behavior is intentionally raw.
        assert cache.stats()["hits"] == 1
