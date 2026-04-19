"""Tests for get_inbox_stats aggregation used by the dashboard widget."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from src.inbox.models import InboxItem, InboxStatus
from src.inbox.service import get_inbox_stats


def _make(db, user, status, created_delta_days=0):
    item = InboxItem(
        id=uuid.uuid4(),
        user_id=user.id,
        raw_text="Sample job posting " * 8,
        content_hash=str(uuid.uuid4()),
        source="linkedin",
        source_url="https://www.linkedin.com/jobs/view/1",
        status=status,
        created_at=datetime.now(UTC) - timedelta(days=created_delta_days),
    )
    db.add(item)
    db.commit()
    return item


class TestGetInboxStats:
    def test_empty_user_returns_zeros(self, db_session, test_user):
        stats = get_inbox_stats(db_session, test_user.id)
        assert stats == {
            "today_total": 0,
            "pending_active": 0,
            "done_total": 0,
            "error_total": 0,
            "last_received_at": None,
        }

    def test_today_total_counts_items_created_today(self, db_session, test_user):
        _make(db_session, test_user, InboxStatus.PENDING.value, created_delta_days=0)
        _make(db_session, test_user, InboxStatus.DONE.value, created_delta_days=0)
        _make(db_session, test_user, InboxStatus.DONE.value, created_delta_days=5)  # not today

        stats = get_inbox_stats(db_session, test_user.id)
        assert stats["today_total"] == 2

    def test_pending_active_counts_pending_and_processing(self, db_session, test_user):
        _make(db_session, test_user, InboxStatus.PENDING.value)
        _make(db_session, test_user, InboxStatus.PROCESSING.value)
        _make(db_session, test_user, InboxStatus.DONE.value)
        _make(db_session, test_user, InboxStatus.ERROR.value)
        _make(db_session, test_user, InboxStatus.SKIPPED.value)

        stats = get_inbox_stats(db_session, test_user.id)
        assert stats["pending_active"] == 2

    def test_done_total_30d_window(self, db_session, test_user):
        _make(db_session, test_user, InboxStatus.DONE.value, created_delta_days=5)
        _make(db_session, test_user, InboxStatus.DONE.value, created_delta_days=15)
        _make(db_session, test_user, InboxStatus.DONE.value, created_delta_days=40)  # outside window

        stats = get_inbox_stats(db_session, test_user.id)
        assert stats["done_total"] == 2

    def test_error_total_30d_window(self, db_session, test_user):
        _make(db_session, test_user, InboxStatus.ERROR.value, created_delta_days=2)
        _make(db_session, test_user, InboxStatus.ERROR.value, created_delta_days=60)  # too old

        stats = get_inbox_stats(db_session, test_user.id)
        assert stats["error_total"] == 1

    def test_last_received_at_picks_most_recent_any_status(self, db_session, test_user):
        _make(db_session, test_user, InboxStatus.DONE.value, created_delta_days=10)
        _make(db_session, test_user, InboxStatus.ERROR.value, created_delta_days=20)
        latest = _make(db_session, test_user, InboxStatus.PENDING.value, created_delta_days=0)

        stats = get_inbox_stats(db_session, test_user.id)
        assert stats["last_received_at"] is not None
        assert stats["last_received_at"].startswith(latest.created_at.isoformat()[:16])

    def test_stats_isolated_per_user(self, db_session, test_user):
        import uuid as _uuid

        from src.auth.models import User

        other = User(id=_uuid.uuid4(), email="other@example.com", password_hash="$2b$12$fake")
        db_session.add(other)
        db_session.commit()

        _make(db_session, test_user, InboxStatus.DONE.value)
        _make(db_session, other, InboxStatus.DONE.value)

        stats = get_inbox_stats(db_session, test_user.id)
        assert stats["done_total"] == 1  # only own rows
