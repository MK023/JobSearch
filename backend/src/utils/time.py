"""Timezone conversion helpers — keep UTC in the DB, render in Europe/Rome.

The app stores every ``datetime`` as timezone-aware UTC (SQLAlchemy columns
declared ``DateTime(timezone=True)``, ``datetime.now(UTC)`` everywhere).
Templates must convert to local time before formatting, otherwise the
user sees UTC values which are 1h (CET) or 2h (CEST) behind what their
calendar shows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

ITALY_TZ = ZoneInfo("Europe/Rome")


def to_italy(value: Any) -> Any:
    """Convert a UTC datetime (or ISO string) to Europe/Rome.

    Accepts:
    - aware ``datetime`` → converted
    - naive ``datetime`` → assumed UTC, converted
    - ISO 8601 string → parsed + converted
    - ``None`` / empty → returned as-is
    - other types → returned as-is (template-safe)
    """
    if not value:
        return value
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(ITALY_TZ)


def italy_now() -> datetime:
    """Current time in Europe/Rome — for cases where server-side code
    needs to compare against local time directly (rare; prefer UTC).
    """
    return datetime.now(ITALY_TZ)
