"""Tests for interview service and route validation."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from src.analysis.models import AnalysisStatus
from src.interview.models import Interview
from src.interview.routes import EMAIL_RE, URL_RE, VALID_INTERVIEW_TYPES, VALID_PLATFORMS
from src.interview.service import (
    InterviewScheduleData,
    create_or_update_interview,
    delete_interview,
    get_interview_by_analysis,
    get_upcoming_interviews,
)


def _data(**kwargs):
    """Test helper: build InterviewScheduleData from kwargs (backcompat for old test signature)."""
    return InterviewScheduleData(**kwargs)


class TestCreateOrUpdateInterview:
    def test_creates_new_interview(self, db_session, test_analysis):
        scheduled = datetime(2026, 3, 10, 11, 30, tzinfo=UTC)
        interview = create_or_update_interview(db_session, test_analysis.id, _data(scheduled_at=scheduled))
        assert interview is not None
        assert interview.analysis_id == test_analysis.id
        assert interview.scheduled_at == scheduled

    def test_creates_with_all_fields(self, db_session, test_analysis):
        scheduled = datetime(2026, 3, 10, 11, 30, tzinfo=UTC)
        interview = create_or_update_interview(
            db_session,
            test_analysis.id,
            _data(
                scheduled_at=scheduled,
                ends_at=datetime(2026, 3, 10, 12, 15, tzinfo=UTC),
                platform="google_meet",
                interview_type="tecnico",
                interviewer_name="Mario Rossi",
                recruiter_name="Katharina Witting",
                recruiter_email="k.witting@example.com",
                meeting_link="https://meet.google.com/abc-def-ghi",
                meeting_id=None,
                phone_number="+39 02 3046 1972",
                access_pin="333598657",
                notes="Colloquio tecnico Python",
            ),
        )
        assert interview.platform == "google_meet"
        assert interview.interview_type == "tecnico"
        assert interview.interviewer_name == "Mario Rossi"
        assert interview.recruiter_name == "Katharina Witting"
        assert interview.meeting_link == "https://meet.google.com/abc-def-ghi"
        assert interview.access_pin == "333598657"

    def test_updates_existing_interview(self, db_session, test_analysis):
        scheduled = datetime(2026, 3, 10, 11, 30, tzinfo=UTC)
        create_or_update_interview(
            db_session,
            test_analysis.id,
            _data(scheduled_at=scheduled, platform="google_meet", interviewer_name="Old Person"),
        )
        db_session.flush()

        new_scheduled = datetime(2026, 3, 12, 14, 0, tzinfo=UTC)
        updated = create_or_update_interview(
            db_session,
            test_analysis.id,
            _data(
                scheduled_at=new_scheduled,
                platform="teams",
                interviewer_name="New Person",
                meeting_id="123-456-789",
                access_pin="9999",
            ),
        )
        db_session.flush()

        assert updated.scheduled_at == new_scheduled
        assert updated.platform == "teams"
        assert updated.interviewer_name == "New Person"
        assert updated.meeting_id == "123-456-789"
        assert updated.access_pin == "9999"
        interviews = db_session.query(Interview).filter_by(analysis_id=test_analysis.id).all()
        assert len(interviews) == 1

    def test_returns_none_for_missing_analysis(self, db_session):
        fake_id = uuid.uuid4()
        result = create_or_update_interview(db_session, fake_id, _data(scheduled_at=datetime.now(UTC)))
        assert result is None


class TestGetInterviewByAnalysis:
    def test_returns_interview(self, db_session, test_analysis):
        scheduled = datetime(2026, 3, 10, 11, 30, tzinfo=UTC)
        create_or_update_interview(db_session, test_analysis.id, _data(scheduled_at=scheduled))
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
        create_or_update_interview(db_session, test_analysis.id, _data(scheduled_at=scheduled))
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
        create_or_update_interview(db_session, test_analysis.id, _data(scheduled_at=soon))
        test_analysis.status = AnalysisStatus.INTERVIEW
        db_session.flush()

        upcoming = get_upcoming_interviews(db_session)
        assert len(upcoming) == 1

    def test_excludes_past_interviews(self, db_session, test_analysis):
        past = datetime.now(UTC) - timedelta(hours=1)
        create_or_update_interview(db_session, test_analysis.id, _data(scheduled_at=past))
        test_analysis.status = AnalysisStatus.INTERVIEW
        db_session.flush()

        upcoming = get_upcoming_interviews(db_session)
        assert len(upcoming) == 0

    def test_excludes_far_future(self, db_session, test_analysis, test_cv):
        far = datetime.now(UTC) + timedelta(days=5)
        create_or_update_interview(db_session, test_analysis.id, _data(scheduled_at=far))
        test_analysis.status = AnalysisStatus.INTERVIEW
        db_session.flush()

        upcoming = get_upcoming_interviews(db_session)
        assert len(upcoming) == 0

    def test_upcoming_includes_platform(self, db_session, test_analysis):
        soon = datetime.now(UTC) + timedelta(hours=12)
        create_or_update_interview(db_session, test_analysis.id, _data(scheduled_at=soon, platform="teams"))
        test_analysis.status = AnalysisStatus.INTERVIEW
        db_session.flush()

        upcoming = get_upcoming_interviews(db_session)
        assert len(upcoming) == 1
        assert upcoming[0]["platform"] == "teams"


class TestValidation:
    """Tests for route-level validation constants and regex patterns."""

    @pytest.mark.parametrize(
        "platform",
        ["google_meet", "teams", "zoom", "phone", "in_person", "other"],
    )
    def test_valid_platforms(self, platform):
        assert platform in VALID_PLATFORMS

    @pytest.mark.parametrize("platform", ["skype", "virtual", "whatsapp", ""])
    def test_invalid_platforms(self, platform):
        assert platform not in VALID_PLATFORMS

    @pytest.mark.parametrize(
        "itype",
        ["tecnico", "hr", "conoscitivo", "finale", "other"],
    )
    def test_valid_interview_types(self, itype):
        assert itype in VALID_INTERVIEW_TYPES

    @pytest.mark.parametrize("itype", ["virtual", "phone", "in_person", ""])
    def test_old_interview_type_values_rejected(self, itype):
        assert itype not in VALID_INTERVIEW_TYPES

    @pytest.mark.parametrize(
        "email",
        ["user@example.com", "a.b+c@domain.co.uk", "test@test.it"],
    )
    def test_valid_emails(self, email):
        assert EMAIL_RE.match(email)

    @pytest.mark.parametrize(
        "email",
        ["notanemail", "@missing.com", "user@", "user@.com", ""],
    )
    def test_invalid_emails(self, email):
        assert not EMAIL_RE.match(email)

    @pytest.mark.parametrize(
        "url",
        ["https://meet.google.com/abc", "http://example.com", "https://teams.microsoft.com/l/meetup"],
    )
    def test_valid_urls(self, url):
        assert URL_RE.match(url)

    @pytest.mark.parametrize(
        "url",
        ["javascript:alert(1)", "ftp://file.com", "data:text/html,<h1>XSS</h1>", "not-a-url", ""],
    )
    def test_xss_urls_rejected(self, url):
        assert not URL_RE.match(url)
