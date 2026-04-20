"""Tests for inbox-originated notifications.

The old `_inbox_ready` rule was retired — the same inbox-DONE items with
pending JobAnalysis are now surfaced by `_backlog_to_review(source=
'extension')` (see test_notification_center.py::test_backlog_splits_per_source).
Only the inbox-specific error path stays here because failed inbox items
never reach JobAnalysis and are therefore not in the backlog rule's scope.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from src.inbox.models import InboxItem, InboxStatus
from src.notification_center.models import NotificationType
from src.notification_center.service import _inbox_errors


def _make_inbox(db, user, status, analysis_id=None, error=None, processed_delta_days=0):
    item = InboxItem(
        id=uuid.uuid4(),
        user_id=user.id,
        raw_text="Sample job text long enough to satisfy sanitize min length gate blah blah blah.",
        content_hash=str(uuid.uuid4()),
        source="linkedin",
        source_url="https://www.linkedin.com/jobs/view/1",
        status=status,
        analysis_id=analysis_id,
        error_message=error,
        processed_at=datetime.now(UTC) - timedelta(days=processed_delta_days),
    )
    db.add(item)
    db.commit()
    return item


class TestInboxErrors:
    def test_no_errors_returns_empty(self, db_session, test_user):
        assert _inbox_errors(db_session) == []

    def test_single_error_surfaced_with_message(self, db_session, test_user):
        _make_inbox(
            db_session,
            test_user,
            InboxStatus.ERROR.value,
            error="No CV on file",
        )

        result = _inbox_errors(db_session)
        assert len(result) == 1
        n = result[0]
        assert n.type == NotificationType.INBOX_ERROR
        assert n.sticky is True  # errors require attention
        assert "No CV on file" in n.body
        assert "linkedin" in n.title

    def test_multiple_errors_aggregate_into_single_notification(self, db_session, test_user):
        for i in range(3):
            _make_inbox(db_session, test_user, InboxStatus.ERROR.value, error=f"err {i}")

        result = _inbox_errors(db_session)
        assert len(result) == 1  # aggregated
        assert result[0].type == NotificationType.INBOX_ERROR
        assert "3 errori" in result[0].title
        # aggregated id does not contain a single uuid
        assert "aggregated" in result[0].id

    def test_error_older_than_7d_not_surfaced(self, db_session, test_user):
        _make_inbox(
            db_session,
            test_user,
            InboxStatus.ERROR.value,
            error="stale error",
            processed_delta_days=10,
        )

        assert _inbox_errors(db_session) == []

    def test_error_message_truncated_when_single(self, db_session, test_user):
        long_err = "A" * 500
        _make_inbox(db_session, test_user, InboxStatus.ERROR.value, error=long_err)

        result = _inbox_errors(db_session)
        assert len(result) == 1
        # Single-error path truncates to 200 chars
        assert len(result[0].body) == 200
