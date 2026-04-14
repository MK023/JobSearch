"""Tests for the preferences service (whitelist, cache invalidation, upsert)."""

import pytest

from src.preferences.models import AppPreference
from src.preferences.service import (
    ALLOWED_KEYS,
    _reset_cache_for_tests,
    get_preference,
    set_preference,
)


@pytest.fixture(autouse=True)
def reset_cache():
    _reset_cache_for_tests()
    yield
    _reset_cache_for_tests()


class TestGetPreference:
    def test_returns_default_when_key_missing(self, db_session):
        assert get_preference(db_session, "ai_sonnet_fallback_on_low_confidence", default=False) is False
        assert get_preference(db_session, "ai_sonnet_fallback_on_low_confidence", default=42) == 42

    def test_returns_default_for_non_whitelisted_key(self, db_session):
        # Even if the key somehow existed in DB, the service must reject it.
        db_session.add(AppPreference(key="not_whitelisted", value=True))
        db_session.commit()
        assert get_preference(db_session, "not_whitelisted", default="SAFE") == "SAFE"

    def test_reads_persisted_value(self, db_session):
        db_session.add(AppPreference(key="ai_sonnet_fallback_on_low_confidence", value=True))
        db_session.commit()
        assert get_preference(db_session, "ai_sonnet_fallback_on_low_confidence", default=False) is True

    def test_caches_reads(self, db_session):
        db_session.add(AppPreference(key="ai_sonnet_fallback_on_low_confidence", value=True))
        db_session.commit()
        first = get_preference(db_session, "ai_sonnet_fallback_on_low_confidence", default=False)
        # Mutate the DB directly — the cached value should win
        db_session.query(AppPreference).filter(AppPreference.key == "ai_sonnet_fallback_on_low_confidence").update(
            {"value": False}
        )
        db_session.commit()
        assert first is True
        assert get_preference(db_session, "ai_sonnet_fallback_on_low_confidence", default=None) is True


class TestSetPreference:
    def test_inserts_new_key(self, db_session):
        set_preference(db_session, "ai_sonnet_fallback_on_low_confidence", True)
        row = (
            db_session.query(AppPreference).filter(AppPreference.key == "ai_sonnet_fallback_on_low_confidence").first()
        )
        assert row is not None
        assert row.value is True

    def test_upserts_existing_key(self, db_session):
        set_preference(db_session, "ai_sonnet_fallback_on_low_confidence", True)
        set_preference(db_session, "ai_sonnet_fallback_on_low_confidence", False)
        row = (
            db_session.query(AppPreference).filter(AppPreference.key == "ai_sonnet_fallback_on_low_confidence").first()
        )
        assert row.value is False
        assert db_session.query(AppPreference).count() == 1

    def test_rejects_non_whitelisted_key(self, db_session):
        with pytest.raises(ValueError, match="not whitelisted"):
            set_preference(db_session, "malicious_key", True)

    def test_invalidates_cache_on_set(self, db_session):
        set_preference(db_session, "ai_sonnet_fallback_on_low_confidence", False)
        assert get_preference(db_session, "ai_sonnet_fallback_on_low_confidence", default=None) is False
        set_preference(db_session, "ai_sonnet_fallback_on_low_confidence", True)
        # After set, the cache is cleared → next read reflects the new value.
        assert get_preference(db_session, "ai_sonnet_fallback_on_low_confidence", default=None) is True


class TestAllowedKeys:
    def test_current_allowed_set_is_frozen(self):
        assert isinstance(ALLOWED_KEYS, frozenset)

    def test_expected_key_present(self):
        assert "ai_sonnet_fallback_on_low_confidence" in ALLOWED_KEYS
