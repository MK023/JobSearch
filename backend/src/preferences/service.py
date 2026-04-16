"""Get/set persisted runtime preferences with whitelist + in-memory cache."""

from typing import Any

from sqlalchemy.orm import Session

from .models import AppPreference

# Whitelist of keys the UI and API are allowed to read/write. Keys not in this
# set cannot be accessed, even by authenticated users — this is the single
# choke point that prevents JSONB injection or dangerous arbitrary writes.
ALLOWED_KEYS: frozenset[str] = frozenset(
    {
        "ai_sonnet_fallback_on_low_confidence",
        "followup_reminder_days",
        "budget_warning_threshold",
        "budget_critical_threshold",
        "interview_no_outcome_days",
    }
)

# Process-local cache. A set() in any worker invalidates this worker's cache
# immediately; other workers pick up the new value on their next DB read
# (max staleness = no explicit miss, next read hits DB fresh).
_cache: dict[str, Any] = {}
_NOT_CACHED = object()


def get_preference(db: Session, key: str, default: Any = None) -> Any:
    """Read a preference; returns `default` if not set or not whitelisted.

    Whitelisted keys are cached per-process ONLY when a DB row exists. Missing
    keys re-hit the DB on every call (trivial cost — indexed PK lookup) so the
    caller's `default` is always honored.
    """
    if key not in ALLOWED_KEYS:
        return default
    cached = _cache.get(key, _NOT_CACHED)
    if cached is not _NOT_CACHED:
        return cached
    row = db.query(AppPreference).filter(AppPreference.key == key).first()
    if row is None:
        return default
    _cache[key] = row.value
    return row.value


def set_preference(db: Session, key: str, value: Any) -> None:
    """Upsert a preference. Rejects keys not in ALLOWED_KEYS.

    Invalidates the process cache for that key so the next read hits the DB.
    """
    if key not in ALLOWED_KEYS:
        raise ValueError(f"Preference key {key!r} is not whitelisted")
    row = db.query(AppPreference).filter(AppPreference.key == key).first()
    if row is None:
        row = AppPreference(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()
    _cache.pop(key, None)


def _reset_cache_for_tests() -> None:
    """Test-only helper — clears the in-memory cache between tests."""
    _cache.clear()
