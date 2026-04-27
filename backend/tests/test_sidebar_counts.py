"""Tests for the sidebar counts endpoint and its in-memory cache."""

from __future__ import annotations

import time
import uuid

import pytest

from src.agenda.models import TodoItem
from src.analysis.models import AnalysisStatus, JobAnalysis
from src.notification_center import counts


@pytest.fixture(autouse=True)
def _clear_cache():
    """Each test starts with an empty cache so TTL behaviour is deterministic."""
    counts.invalidate_cache()
    yield
    counts.invalidate_cache()


def _add_pending_analysis(db, test_cv, *, n: int = 1) -> None:
    for _ in range(n):
        db.add(
            JobAnalysis(
                id=uuid.uuid4(),
                cv_id=test_cv.id,
                job_description="jd",
                company="c",
                role="r",
                status=AnalysisStatus.PENDING.value,
            )
        )
    db.flush()


def _add_open_todo(db, *, n: int = 1) -> None:
    for _ in range(n):
        db.add(TodoItem(text="t", done=False))
    db.flush()


def test_counts_reflect_db_state(db_session, test_cv):
    _add_pending_analysis(db_session, test_cv, n=3)
    _add_open_todo(db_session, n=2)

    result = counts.get_sidebar_counts(db_session, force=True)

    assert result["pending_count"] == 3
    assert result["agenda_count"] == 2
    assert result["interview_count"] == 0
    assert result["notification_count"] >= 0
    assert isinstance(result["analytics_available"], bool)


def test_cache_returns_stale_value_within_ttl(db_session, test_cv):
    _add_pending_analysis(db_session, test_cv, n=1)
    first = counts.get_sidebar_counts(db_session)
    assert first["pending_count"] == 1

    _add_pending_analysis(db_session, test_cv, n=5)
    cached = counts.get_sidebar_counts(db_session)

    # TTL still warm, the cache lies on purpose to absorb DB load.
    assert cached["pending_count"] == 1


def test_cache_recomputes_after_ttl(db_session, test_cv, monkeypatch):
    _add_pending_analysis(db_session, test_cv, n=1)
    counts.get_sidebar_counts(db_session)

    _add_pending_analysis(db_session, test_cv, n=4)

    # Jump past the TTL by patching monotonic — keeps the test fast and
    # decoupled from real wall-clock sleeps.
    base = time.monotonic()
    monkeypatch.setattr(counts.time, "monotonic", lambda: base + 999)

    fresh = counts.get_sidebar_counts(db_session)
    assert fresh["pending_count"] == 5


def test_force_bypasses_cache(db_session, test_cv):
    _add_pending_analysis(db_session, test_cv, n=1)
    counts.get_sidebar_counts(db_session)

    _add_pending_analysis(db_session, test_cv, n=2)
    forced = counts.get_sidebar_counts(db_session, force=True)

    assert forced["pending_count"] == 3


def test_invalidate_cache_drops_stored_value(db_session, test_cv):
    _add_pending_analysis(db_session, test_cv, n=1)
    counts.get_sidebar_counts(db_session)
    assert counts._cache["value"] is not None

    counts.invalidate_cache()
    assert counts._cache["value"] is None
    assert counts._cache["expires_at"] == 0.0
