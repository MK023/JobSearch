"""Tests for interview service."""

import uuid
from datetime import UTC, datetime, timedelta

from src.analysis.models import AnalysisStatus
from src.interview.models import Interview
from src.interview.service import (
    create_or_update_interview,
    delete_interview,
    get_interview_by_analysis,
    get_upcoming_interviews,
)


class TestCreateOrUpdateInterview:
    def test_creates_new_interview(self, db_session, test_analysis):
        scheduled = datetime(2026, 3, 10, 11, 30, tzinfo=UTC)
        interview = create_or_update_interview(
            db_session, test_analysis.id, scheduled_at=scheduled
        )
        assert interview is not None
        assert interview.analysis_id == test_analysis.id
        assert interview.scheduled_at == scheduled

    def test_creates_with_all_fields(self, db_session, test_analysis):
        scheduled = datetime(2026, 3, 10, 11, 30, tzinfo=UTC)
        interview = create_or_update_interview(
            db_session,
            test_analysis.id,
            scheduled_at=scheduled,
            ends_at=datetime(2026, 3, 10, 12, 15, tzinfo=UTC),
            interview_type="virtual",
            recruiter_name="Katharina Witting",
            recruiter_email="k.witting@example.com",
            meeting_link="https://meet.google.com/abc-def-ghi",
            phone_number="+39 02 3046 1972",
            phone_pin="333598657",
            notes="Colloquio recruiting",
        )
        assert interview.recruiter_name == "Katharina Witting"
        assert interview.interview_type == "virtual"
        assert interview.meeting_link == "https://meet.google.com/abc-def-ghi"

    def test_updates_existing_interview(self, db_session, test_analysis):
        scheduled = datetime(2026, 3, 10, 11, 30, tzinfo=UTC)
        create_or_update_interview(db_session, test_analysis.id, scheduled_at=scheduled)
        db_session.flush()

        new_scheduled = datetime(2026, 3, 12, 14, 0, tzinfo=UTC)
        updated = create_or_update_interview(
            db_session, test_analysis.id, scheduled_at=new_scheduled, recruiter_name="New Person"
        )
        db_session.flush()

        assert updated.scheduled_at == new_scheduled
        assert updated.recruiter_name == "New Person"
        interviews = db_session.query(Interview).filter_by(analysis_id=test_analysis.id).all()
        assert len(interviews) == 1

    def test_returns_none_for_missing_analysis(self, db_session):
        fake_id = uuid.uuid4()
        result = create_or_update_interview(
            db_session, fake_id, scheduled_at=datetime.now(UTC)
        )
        assert result is None


class TestGetInterviewByAnalysis:
    def test_returns_interview(self, db_session, test_analysis):
        scheduled = datetime(2026, 3, 10, 11, 30, tzinfo=UTC)
        create_or_update_interview(db_session, test_analysis.id, scheduled_at=scheduled)
        db_session.flush()

        result = get_interview_by_analysis(db_session, test_analysis.id)
        assert result is not None
        # SQLite drops timezone info on round-trip; compare naive values
        assert result.scheduled_at.replace(tzinfo=None) == scheduled.replace(tzinfo=None)

    def test_returns_none_when_no_interview(self, db_session, test_analysis):
        result = get_interview_by_analysis(db_session, test_analysis.id)
        assert result is None


class TestDeleteInterview:
    def test_deletes_existing(self, db_session, test_analysis):
        scheduled = datetime(2026, 3, 10, 11, 30, tzinfo=UTC)
        create_or_update_interview(db_session, test_analysis.id, scheduled_at=scheduled)
        db_session.flush()

        deleted = delete_interview(db_session, test_analysis.id)
        assert deleted is True
        assert get_interview_by_analysis(db_session, test_analysis.id) is None

    def test_returns_false_when_none(self, db_session, test_analysis):
        deleted = delete_interview(db_session, test_analysis.id)
        assert deleted is False


class TestGetUpcomingInterviews:
    def test_returns_interviews_within_48h(self, db_session, test_analysis):
        soon = datetime.now(UTC) + timedelta(hours=12)
        create_or_update_interview(db_session, test_analysis.id, scheduled_at=soon)
        test_analysis.status = AnalysisStatus.INTERVIEW
        db_session.flush()

        upcoming = get_upcoming_interviews(db_session)
        assert len(upcoming) == 1

    def test_excludes_past_interviews(self, db_session, test_analysis):
        past = datetime.now(UTC) - timedelta(hours=1)
        create_or_update_interview(db_session, test_analysis.id, scheduled_at=past)
        test_analysis.status = AnalysisStatus.INTERVIEW
        db_session.flush()

        upcoming = get_upcoming_interviews(db_session)
        assert len(upcoming) == 0

    def test_excludes_far_future(self, db_session, test_analysis, test_cv):
        far = datetime.now(UTC) + timedelta(days=5)
        create_or_update_interview(db_session, test_analysis.id, scheduled_at=far)
        test_analysis.status = AnalysisStatus.INTERVIEW
        db_session.flush()

        upcoming = get_upcoming_interviews(db_session)
        assert len(upcoming) == 0
