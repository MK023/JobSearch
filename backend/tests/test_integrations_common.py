"""Test dei tre helper estratti in ``src.integrations._common``.

Coverage target: ≥80% sulle linee di ``_common.py`` (Quality Gate SonarCloud).
Tre helper × happy/edge/None = 12 test, behavior-preserving rispetto agli
adapter originali pre-PR4.
"""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from src.integrations._common import parse_iso_datetime, record_error, safe_str

# ──────────────────────────────────────────────────────────────────────
# safe_str
# ──────────────────────────────────────────────────────────────────────


def test_safe_str_happy_path_strips_and_clips() -> None:
    assert safe_str("  hello  ", 10) == "hello"


def test_safe_str_clips_to_max_len() -> None:
    assert safe_str("abcdefghij", 5) == "abcde"


def test_safe_str_returns_empty_on_none() -> None:
    assert safe_str(None, 5) == ""


def test_safe_str_coerces_non_string_values() -> None:
    # Replica il comportamento adapter: ``str(int).strip()`` → ``"42"``.
    assert safe_str(42, 10) == "42"


# ──────────────────────────────────────────────────────────────────────
# parse_iso_datetime
# ──────────────────────────────────────────────────────────────────────


def test_parse_iso_datetime_with_z_suffix() -> None:
    result = parse_iso_datetime("2024-06-01T10:30:00Z")
    assert result == datetime(2024, 6, 1, 10, 30, 0, tzinfo=UTC)


def test_parse_iso_datetime_naive_input_gets_utc() -> None:
    # Replica il comportamento Jobicy/altri: stringa senza timezone → forzata UTC.
    result = parse_iso_datetime("2024-06-01 10:30:00")
    assert result == datetime(2024, 6, 1, 10, 30, 0, tzinfo=UTC)


def test_parse_iso_datetime_returns_none_on_empty() -> None:
    assert parse_iso_datetime("") is None
    assert parse_iso_datetime(None) is None


def test_parse_iso_datetime_returns_none_on_garbage() -> None:
    assert parse_iso_datetime("not a date") is None


# ──────────────────────────────────────────────────────────────────────
# record_error
# ──────────────────────────────────────────────────────────────────────


def _install_fake_sentry(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Installa un fake ``sentry_sdk`` con ``add_breadcrumb`` mockato.

    Usiamo un module fittizio iniettato in ``sys.modules`` perché
    ``record_error`` fa lazy import (``import sentry_sdk`` interno alla
    funzione) e ``contextlib.suppress`` ingoierebbe ImportError.
    """
    fake = types.ModuleType("sentry_sdk")
    breadcrumb = MagicMock()
    fake.add_breadcrumb = breadcrumb  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
    return breadcrumb


def test_record_error_emits_breadcrumb_no_context(monkeypatch: pytest.MonkeyPatch) -> None:
    breadcrumb = _install_fake_sentry(monkeypatch)
    record_error(ValueError("boom"), source="remoteok")
    breadcrumb.assert_called_once_with(
        category="remoteok",
        message="remoteok fetch failed: ValueError",
        level="warning",
    )


def test_record_error_emits_breadcrumb_with_page_kwarg(monkeypatch: pytest.MonkeyPatch) -> None:
    breadcrumb = _install_fake_sentry(monkeypatch)
    record_error(RuntimeError("nope"), source="adzuna", page=2)
    breadcrumb.assert_called_once_with(
        category="adzuna",
        message="adzuna fetch failed page=2: RuntimeError",
        level="warning",
    )


def test_record_error_emits_breadcrumb_with_category_kwarg(monkeypatch: pytest.MonkeyPatch) -> None:
    breadcrumb = _install_fake_sentry(monkeypatch)
    record_error(KeyError("x"), source="weworkremotely", category="remote-devops-sysadmin-jobs")
    breadcrumb.assert_called_once_with(
        category="weworkremotely",
        message="weworkremotely fetch failed category=remote-devops-sysadmin-jobs: KeyError",
        level="warning",
    )


def test_record_error_swallows_when_sentry_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    # Forza l'import interno a fallire: contextlib.suppress deve mangiarsi tutto.
    monkeypatch.setitem(sys.modules, "sentry_sdk", None)
    record_error(ValueError("no sentry"), source="adzuna")  # not raises
