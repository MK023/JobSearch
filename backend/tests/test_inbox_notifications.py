"""Tests for inbox-originated notifications."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from src.analysis.models import AnalysisStatus, JobAnalysis
from src.inbox.models import InboxItem, InboxStatus
from src.notification_center.models import NotificationType
from src.notification_center.service import _inbox_errors, _inbox_ready


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


class TestInboxReady:
    def test_no_done_items_returns_empty(self, db_session, test_user):
        assert _inbox_ready(db_session) == []

    def test_done_item_with_pending_analysis_triggers(self, db_session, test_user, test_cv):
        analysis = JobAnalysis(
            id=uuid.uuid4(),
            cv_id=test_cv.id,
            job_description="x",
            status=AnalysisStatus.PENDING.value,
        )
        db_session.add(analysis)
        db_session.commit()
        _make_inbox(db_session, test_user, InboxStatus.DONE.value, analysis_id=analysis.id)

        result = _inbox_ready(db_session)
        assert len(result) == 1
        assert result[0].type == NotificationType.INBOX_ANALYSIS_READY
        assert "1 nuova analisi" in result[0].title
        assert result[0].action_url == "/history#valutazione"

    def test_done_item_with_triaged_analysis_not_counted(self, db_session, test_user, test_cv):
        analysis = JobAnalysis(
            id=uuid.uuid4(),
            cv_id=test_cv.id,
            job_description="x",
            status=AnalysisStatus.APPLIED.value,  # already triaged
        )
        db_session.add(analysis)
        db_session.commit()
        _make_inbox(db_session, test_user, InboxStatus.DONE.value, analysis_id=analysis.id)

        assert _inbox_ready(db_session) == []

    def test_old_items_outside_7d_window_not_counted(self, db_session, test_user, test_cv):
        analysis = JobAnalysis(
            id=uuid.uuid4(),
            cv_id=test_cv.id,
            job_description="x",
            status=AnalysisStatus.PENDING.value,
        )
        db_session.add(analysis)
        db_session.commit()
        _make_inbox(
            db_session,
            test_user,
            InboxStatus.DONE.value,
            analysis_id=analysis.id,
            processed_delta_days=10,
        )

        assert _inbox_ready(db_session) == []

    def test_multiple_done_items_aggregates_count(self, db_session, test_user, test_cv):
        for _ in range(3):
            analysis = JobAnalysis(
                id=uuid.uuid4(),
                cv_id=test_cv.id,
                job_description="x",
                status=AnalysisStatus.PENDING.value,
            )
            db_session.add(analysis)
            db_session.commit()
            _make_inbox(db_session, test_user, InboxStatus.DONE.value, analysis_id=analysis.id)

        result = _inbox_ready(db_session)
        assert len(result) == 1  # aggregated
        assert result[0].title == "3 nuove analisi dal Chrome extension"


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
