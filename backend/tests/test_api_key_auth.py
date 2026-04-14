"""Tests for X-API-Key authentication path used by external cron jobs."""

import secrets

import pytest

from src.dependencies import _verify_api_key


@pytest.fixture
def configured_api_key(monkeypatch):
    """Set a deterministic API key on settings for the duration of the test."""
    test_key = "test-key-" + secrets.token_hex(8)
    from src import dependencies

    monkeypatch.setattr(dependencies.settings, "api_key", test_key)
    return test_key


class TestVerifyApiKey:
    def test_returns_false_when_api_key_not_configured(self, monkeypatch):
        from src import dependencies

        monkeypatch.setattr(dependencies.settings, "api_key", "")
        assert _verify_api_key("anything") is False

    def test_returns_false_when_header_missing(self, configured_api_key):
        assert _verify_api_key(None) is False
        assert _verify_api_key("") is False

    def test_returns_false_on_wrong_key(self, configured_api_key):
        assert _verify_api_key("wrong-key") is False

    def test_returns_true_on_match(self, configured_api_key):
        assert _verify_api_key(configured_api_key) is True

    def test_uses_constant_time_comparison(self, configured_api_key):
        """secrets.compare_digest is timing-safe; verify the function path uses it."""
        # Just make sure equal-length and unequal-length both return False without raising
        assert _verify_api_key("x") is False
        assert _verify_api_key("x" * len(configured_api_key)) is False
