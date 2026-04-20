"""Real-DB tests for the notification center aggregator.

No mocks of the session — every rule is exercised against actual rows in
the SQLite test DB and asserted by id / severity / count. This is the
kind of test Marco wants: a change in the service must change the
observable output, not just flip a mock.
"""

import uuid
from datetime import UTC, datetime, timedelta

from src.analysis.models import AnalysisSource, AnalysisStatus, JobAnalysis
from src.dashboard.service import get_or_create_settings
from src.interview.models import Interview, InterviewOutcome
from src.notification_center.service import (
    _BACKLOG_THRESHOLD,
    _BUDGET_WARNING_DEFAULT,
    _INTERVIEW_NO_OUTCOME_DAYS_DEFAULT,
    _INTERVIEW_UPCOMING_HOURS,
    dismiss_notification,
    get_notifications,
    get_unread_count,
    undismiss_notification,
)


def _make_analysis(
    db_session,
    test_cv,
    *,
    status: AnalysisStatus,
    score: int = 60,
    applied_days_ago: int | None = None,
    source: str = AnalysisSource.COWORK.value,
):
    a = JobAnalysis(
        id=uuid.uuid4(),
        cv_id=test_cv.id,
        job_description="x",
        company="Acme",
        role="Engineer",
        score=score,
        status=status.value,
        source=source,
        created_at=datetime.now(UTC),
        applied_at=(datetime.now(UTC) - timedelta(days=applied_days_ago)) if applied_days_ago is not None else None,
    )
    db_session.add(a)
    db_session.commit()
    return a


class TestEmptyState:
    def test_no_notifications_when_nothing_matters(self, db_session):
        notifs = get_notifications(db_session)
        # Filter out backup_stale — it fires legitimately when no R2 backups exist
        notifs = [n for n in notifs if n.type.value != "backup_stale"]
        assert notifs == []


class TestUpcomingInterview:
    def test_interview_within_24h_triggers_critical(self, db_session, test_cv):
        a = _make_analysis(db_session, test_cv, status=AnalysisStatus.INTERVIEW)
        when = datetime.now(UTC) + timedelta(hours=_INTERVIEW_UPCOMING_HOURS - 1)
        db_session.add(Interview(analysis_id=a.id, round_number=1, scheduled_at=when))
        db_session.commit()

        notifs = get_notifications(db_session)
        assert len(notifs) == 1
        assert notifs[0].id == f"interview:{a.id}"
        assert notifs[0].severity.value == "critical"
        assert notifs[0].dismissible is True
        assert notifs[0].sticky is True

    def test_interview_farther_than_24h_does_not_trigger(self, db_session, test_cv):
        a = _make_analysis(db_session, test_cv, status=AnalysisStatus.INTERVIEW)
        when = datetime.now(UTC) + timedelta(hours=_INTERVIEW_UPCOMING_HOURS + 5)
        db_session.add(Interview(analysis_id=a.id, round_number=1, scheduled_at=when))
        db_session.commit()

        assert get_notifications(db_session) == []


class TestLowBudget:
    def test_no_notification_when_no_budget_set(self, db_session):
        # budget=0 means "no limit" — must NOT surface a warning.
        assert get_notifications(db_session) == []

    def test_warning_when_remaining_below_one(self, db_session):
        s = get_or_create_settings(db_session)
        s.anthropic_budget = 2.0
        s.total_cost_usd = 2.0 - (_BUDGET_WARNING_DEFAULT - 0.1)  # remaining ≈ 0.9
        db_session.commit()

        notifs = get_notifications(db_session)
        assert len(notifs) == 1
        assert notifs[0].id == "budget:anthropic"
        assert notifs[0].severity.value == "warning"

    def test_critical_when_remaining_below_half(self, db_session):
        s = get_or_create_settings(db_session)
        s.anthropic_budget = 2.0
        s.total_cost_usd = 1.7  # remaining 0.3
        db_session.commit()

        notifs = get_notifications(db_session)
        assert len(notifs) == 1
        assert notifs[0].severity.value == "critical"

    def test_silent_when_remaining_above_one(self, db_session):
        s = get_or_create_settings(db_session)
        s.anthropic_budget = 10.0
        s.total_cost_usd = 1.0  # remaining 9.0
        db_session.commit()

        assert get_notifications(db_session) == []


class TestInterviewWithoutOutcome:
    def test_past_interview_without_outcome_surfaces(self, db_session, test_cv):
        a = _make_analysis(db_session, test_cv, status=AnalysisStatus.INTERVIEW)
        when = datetime.now(UTC) - timedelta(days=_INTERVIEW_NO_OUTCOME_DAYS_DEFAULT + 1)
        iv = Interview(analysis_id=a.id, round_number=1, scheduled_at=when, outcome=None)
        db_session.add(iv)
        db_session.commit()

        notifs = get_notifications(db_session)
        assert any(n.id == f"interview_outcome:{iv.id}" for n in notifs)
        n = next(n for n in notifs if n.id == f"interview_outcome:{iv.id}")
        assert n.severity.value == "warning"
        assert n.action_url == f"/analysis/{a.id}"

    def test_logged_outcome_clears_notification(self, db_session, test_cv):
        a = _make_analysis(db_session, test_cv, status=AnalysisStatus.INTERVIEW)
        when = datetime.now(UTC) - timedelta(days=_INTERVIEW_NO_OUTCOME_DAYS_DEFAULT + 1)
        iv = Interview(analysis_id=a.id, round_number=1, scheduled_at=when, outcome=InterviewOutcome.PASSED.value)
        db_session.add(iv)
        db_session.commit()

        assert get_notifications(db_session) == []

    def test_recent_interview_without_outcome_does_not_surface(self, db_session, test_cv):
        """An interview 1 day in the past is not yet 'late' — 3 days is the threshold."""
        a = _make_analysis(db_session, test_cv, status=AnalysisStatus.INTERVIEW)
        when = datetime.now(UTC) - timedelta(days=1)
        db_session.add(Interview(analysis_id=a.id, round_number=1, scheduled_at=when))
        db_session.commit()

        # Upcoming rule also does not fire (the scheduled_at is in the past).
        assert get_notifications(db_session) == []


class TestFollowupDue:
    def test_applied_beyond_threshold_shows_as_info_dismissible(self, db_session, test_cv):
        _make_analysis(db_session, test_cv, status=AnalysisStatus.APPLIED, applied_days_ago=10)
        notifs = get_notifications(db_session)
        followups = [n for n in notifs if n.type.value == "followup_due"]
        assert len(followups) == 1
        assert followups[0].severity.value == "info"
        assert followups[0].dismissible is True
        assert followups[0].sticky is False

    def test_aggregate_action_url_includes_since(self, db_session, test_cv):
        # 3 applications beyond follow-up threshold -> aggregated card
        # whose action_url should carry ?since=<oldest applied_at> so the
        # /agenda page can highlight exactly these rows.
        for days_ago in (7, 10, 15):
            _make_analysis(db_session, test_cv, status=AnalysisStatus.APPLIED, applied_days_ago=days_ago)
        notifs = get_notifications(db_session)
        aggregated = next(n for n in notifs if n.id.startswith("followup:aggregated:"))
        assert aggregated.action_url.startswith("/agenda?since=")


class TestBacklogToReview:
    def test_few_pending_does_not_trigger(self, db_session, test_cv):
        for _ in range(_BACKLOG_THRESHOLD - 1):
            _make_analysis(db_session, test_cv, status=AnalysisStatus.PENDING)
        notifs = [n for n in get_notifications(db_session) if n.type.value == "backlog_to_review"]
        assert notifs == []

    def test_many_pending_surfaces_single_notification(self, db_session, test_cv):
        for _ in range(_BACKLOG_THRESHOLD + 3):
            _make_analysis(db_session, test_cv, status=AnalysisStatus.PENDING)
        notifs = [n for n in get_notifications(db_session) if n.type.value == "backlog_to_review"]
        assert len(notifs) == 1
        assert notifs[0].dismissible is True

    def test_backlog_splits_per_source(self, db_session, test_cv):
        # Extension + Cowork pending items in the same DB -> two distinct
        # backlog notifications, each with its own title, body, and
        # source-scoped action_url. This is the core of the "microservice"
        # behavior Marco wants.
        for _ in range(2):
            _make_analysis(db_session, test_cv, status=AnalysisStatus.PENDING, source=AnalysisSource.EXTENSION.value)
        _make_analysis(db_session, test_cv, status=AnalysisStatus.PENDING, source=AnalysisSource.COWORK.value)
        backlog = [n for n in get_notifications(db_session) if n.type.value == "backlog_to_review"]
        sources = {n.id.split(":")[2] for n in backlog}
        assert sources == {"extension", "cowork"}
        for n in backlog:
            assert "source=" in n.action_url
            assert "?since=" in n.action_url

    def test_backlog_action_url_includes_since(self, db_session, test_cv):
        # oldest pending → oldest created_at becomes the `since` anchor
        for _ in range(_BACKLOG_THRESHOLD + 2):
            _make_analysis(db_session, test_cv, status=AnalysisStatus.PENDING)
        notif = next(n for n in get_notifications(db_session) if n.type.value == "backlog_to_review")
        assert notif.action_url.startswith("/history?since=")


class TestSinceHelpers:
    """`_with_since` + `_parse_since` surface the `?since=<ISO>` drill-down
    query param so destination pages can highlight the aggregated items."""

    def test_with_since_appends_iso_timestamp(self):
        from src.notification_center.service import _with_since

        ts = datetime(2026, 4, 20, 10, 30, tzinfo=UTC)
        assert _with_since("/agenda", ts) == "/agenda?since=2026-04-20T10:30:00+00:00"

    def test_with_since_none_returns_url_unchanged(self):
        from src.notification_center.service import _with_since

        assert _with_since("/agenda", None) == "/agenda"

    def test_parse_since_reads_iso(self):
        from src.pages import _parse_since

        class _FakeRequest:
            query_params = {"since": "2026-04-20T10:30:00+00:00"}

        result = _parse_since(_FakeRequest())
        assert result == datetime(2026, 4, 20, 10, 30, tzinfo=UTC)

    def test_parse_since_missing_returns_none(self):
        from src.pages import _parse_since

        class _FakeRequest:
            query_params: dict[str, str] = {}

        assert _parse_since(_FakeRequest()) is None

    def test_parse_since_malformed_returns_none(self):
        from src.pages import _parse_since

        class _FakeRequest:
            query_params = {"since": "not-a-date"}

        assert _parse_since(_FakeRequest()) is None


class TestOrdering:
    def test_critical_comes_before_warning_before_info(self, db_session, test_cv):
        # Critical: upcoming interview
        a1 = _make_analysis(db_session, test_cv, status=AnalysisStatus.INTERVIEW)
        db_session.add(
            Interview(
                analysis_id=a1.id,
                round_number=1,
                scheduled_at=datetime.now(UTC) + timedelta(hours=5),
            )
        )
        # Warning: past interview without outcome
        a2 = _make_analysis(db_session, test_cv, status=AnalysisStatus.INTERVIEW)
        db_session.add(
            Interview(
                analysis_id=a2.id,
                round_number=1,
                scheduled_at=datetime.now(UTC) - timedelta(days=_INTERVIEW_NO_OUTCOME_DAYS_DEFAULT + 1),
            )
        )
        # Info: followup due
        _make_analysis(db_session, test_cv, status=AnalysisStatus.APPLIED, applied_days_ago=10)
        db_session.commit()

        notifs = get_notifications(db_session)
        severities = [n.severity.value for n in notifs]
        # All three present and ordered
        assert severities.index("critical") < severities.index("warning") < severities.index("info")


class TestUnreadCount:
    def test_matches_len_of_get_notifications(self, db_session, test_cv):
        for _ in range(_BACKLOG_THRESHOLD + 5):
            _make_analysis(db_session, test_cv, status=AnalysisStatus.PENDING)
        assert get_unread_count(db_session) == len(get_notifications(db_session))


class TestDismissServerSide:
    def test_dismiss_removes_from_list_and_count(self, db_session, test_cv):
        _make_analysis(db_session, test_cv, status=AnalysisStatus.APPLIED, applied_days_ago=10)
        db_session.commit()

        before = get_notifications(db_session)
        assert len(before) == 1
        nid = before[0].id

        created = dismiss_notification(db_session, nid)
        db_session.commit()
        assert created is True

        after = get_notifications(db_session)
        assert len(after) == 0
        assert get_unread_count(db_session) == 0

    def test_dismiss_idempotent(self, db_session, test_cv):
        _make_analysis(db_session, test_cv, status=AnalysisStatus.APPLIED, applied_days_ago=10)
        db_session.commit()

        nid = get_notifications(db_session)[0].id
        assert dismiss_notification(db_session, nid) is True
        assert dismiss_notification(db_session, nid) is False
        db_session.commit()

    def test_undismiss_restores_notification(self, db_session, test_cv):
        _make_analysis(db_session, test_cv, status=AnalysisStatus.APPLIED, applied_days_ago=10)
        db_session.commit()

        nid = get_notifications(db_session)[0].id
        dismiss_notification(db_session, nid)
        db_session.commit()
        assert get_unread_count(db_session) == 0

        removed = undismiss_notification(db_session, nid)
        db_session.commit()
        assert removed is True
        assert get_unread_count(db_session) == 1

    def test_dismiss_interview_notification(self, db_session, test_cv):
        """Interview notifications can now be dismissed server-side."""
        a = _make_analysis(db_session, test_cv, status=AnalysisStatus.INTERVIEW)
        when = datetime.now(UTC) + timedelta(hours=_INTERVIEW_UPCOMING_HOURS - 1)
        db_session.add(Interview(analysis_id=a.id, round_number=1, scheduled_at=when))
        db_session.commit()

        notifs = get_notifications(db_session)
        assert len(notifs) == 1
        nid = notifs[0].id

        dismiss_notification(db_session, nid)
        db_session.commit()
        assert get_notifications(db_session) == []
        assert get_unread_count(db_session) == 0
