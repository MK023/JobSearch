"""Tests for Glassdoor integration helpers extracted during SonarCloud refactor.

Covers:
- `_best_match`: match resolution strategy (exact → prefix → substring, min reviews gate).
- `_fetch_and_cache_from_api`: orchestration of API call, match pick, DB+Redis caching,
  and graceful degradation on API errors / no match.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.integrations import glassdoor as gd
from src.integrations.glassdoor import _best_match, _fetch_and_cache_from_api


def _result(name: str, rating: float | None = 4.0, review_count: int = 10, **extra: Any) -> dict[str, Any]:
    """Build a minimal API result row with the fields _best_match inspects."""
    return {"name": name, "rating": rating, "review_count": review_count, **extra}


class TestBestMatch:
    def test_returns_none_when_status_not_ok(self):
        assert _best_match({"status": "ERROR", "data": [_result("Acme")]}, "acme") is None

    def test_returns_none_on_empty_results(self):
        assert _best_match({"status": "OK", "data": []}, "acme") is None

    def test_prefers_exact_name_match(self):
        data = {
            "status": "OK",
            "data": [
                _result("Acme Corporation"),
                _result("Acme"),
                _result("Acme Global"),
            ],
        }
        match = _best_match(data, "Acme")
        assert match is not None
        assert match["name"] == "Acme"

    def test_falls_back_to_prefix_when_no_exact(self):
        data = {"status": "OK", "data": [_result("Acme Corporation")]}
        match = _best_match(data, "acme")
        assert match is not None
        assert match["name"] == "Acme Corporation"

    def test_query_startswith_result_name_also_prefix(self):
        data = {"status": "OK", "data": [_result("Acme")]}
        match = _best_match(data, "acme corp")
        assert match is not None
        assert match["name"] == "Acme"

    def test_falls_back_to_substring(self):
        data = {"status": "OK", "data": [_result("Global Acme Holdings")]}
        match = _best_match(data, "acme")
        assert match is not None
        assert match["name"] == "Global Acme Holdings"

    def test_skips_results_without_rating(self):
        data = {
            "status": "OK",
            "data": [
                _result("Acme", rating=None),
                _result("Acme Global", rating=4.2),
            ],
        }
        match = _best_match(data, "acme")
        assert match is not None
        assert match["name"] == "Acme Global"

    def test_skips_results_below_min_reviews(self):
        data = {
            "status": "OK",
            "data": [
                _result("Acme", review_count=2),
                _result("Acme Partners", review_count=3),
            ],
        }
        match = _best_match(data, "acme")
        assert match is not None
        assert match["name"] == "Acme Partners"

    def test_returns_none_when_no_result_is_usable(self):
        data = {
            "status": "OK",
            "data": [
                _result("Acme", rating=None),
                _result("Acme Partners", review_count=1),
            ],
        }
        assert _best_match(data, "acme") is None


class TestFetchAndCacheFromApi:
    """_fetch_and_cache_from_api orchestrates API → _best_match → persist → Redis.

    We mock every collaborator so the test pins the wiring, not the collaborators'
    internal behaviour.
    """

    @pytest.fixture
    def patched(self, monkeypatch):
        calls: dict[str, Any] = {"api": [], "persist": [], "cache_set": []}

        def fake_call_api(query: str) -> dict[str, Any] | None:
            calls["api"].append(query)
            return {
                "status": "OK",
                "data": [{"name": "Acme", "rating": 4.2, "review_count": 42}],
            }

        def fake_persist(db, normalized, company, parsed):
            calls["persist"].append((normalized, company["name"], parsed.get("glassdoor_rating")))

        monkeypatch.setattr(gd, "_call_api", fake_call_api)
        monkeypatch.setattr(gd, "_persist_glassdoor_cache", fake_persist)
        return calls

    def test_happy_path_returns_parsed_and_writes_both_caches(self, patched, db_session):
        cache_set: list[tuple[str, Any, int]] = []

        class FakeCache:
            def set_json(self, key, value, ttl):
                cache_set.append((key, value, ttl))

        result = _fetch_and_cache_from_api(
            "Acme",
            "acme",
            db_session,
            FakeCache(),
            "glassdoor:acme",
        )
        assert result is not None
        assert result["cached"] is False
        assert result["glassdoor_rating"] == 4.2
        assert patched["api"] == ["Acme"]
        assert patched["persist"] and patched["persist"][0][0] == "acme"
        assert cache_set and cache_set[0][0] == "glassdoor:acme"
        assert cache_set[0][2] == 3600

    def test_works_without_redis_cache(self, patched, db_session):
        result = _fetch_and_cache_from_api("Acme", "acme", db_session, None, "glassdoor:acme")
        assert result is not None
        assert result["cached"] is False

    def test_returns_none_when_api_raises(self, monkeypatch, db_session):
        def boom(query: str):
            raise RuntimeError("network down")

        monkeypatch.setattr(gd, "_call_api", boom)
        assert _fetch_and_cache_from_api("Acme", "acme", db_session, None, "k") is None

    def test_returns_none_when_api_returns_none(self, monkeypatch, db_session):
        monkeypatch.setattr(gd, "_call_api", lambda q: None)
        assert _fetch_and_cache_from_api("Acme", "acme", db_session, None, "k") is None

    def test_returns_none_when_no_match(self, monkeypatch, db_session):
        monkeypatch.setattr(
            gd,
            "_call_api",
            lambda q: {"status": "OK", "data": [{"name": "Foo", "rating": None, "review_count": 0}]},
        )
        persisted: list[Any] = []
        monkeypatch.setattr(gd, "_persist_glassdoor_cache", lambda *a, **kw: persisted.append(a))
        assert _fetch_and_cache_from_api("Acme", "acme", db_session, None, "k") is None
        assert persisted == []
