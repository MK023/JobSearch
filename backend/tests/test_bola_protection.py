"""Regression tests for BOLA (Broken Object-Level Authorization) protection.

get_analysis_by_id now accepts an optional user_id; when provided, the
query is scoped to analyses whose CV belongs to that user. Route handlers
must always pass it.
"""

import uuid

import pytest

from src.analysis.models import JobAnalysis
from src.analysis.service import get_analysis_by_id
from src.auth.models import User
from src.cv.models import CVProfile


@pytest.fixture
def other_user(db_session):
    """A second user, distinct from `test_user`."""
    u = User(id=uuid.uuid4(), email="other@example.com", password_hash="$2b$12$fakehash")
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def other_user_cv(db_session, other_user):
    cv = CVProfile(
        id=uuid.uuid4(),
        user_id=other_user.id,
        raw_text="Other user CV with enough text to pass validation.",
        name="Other User",
    )
    db_session.add(cv)
    db_session.commit()
    return cv


@pytest.fixture
def other_user_analysis(db_session, other_user_cv):
    a = JobAnalysis(
        id=uuid.uuid4(),
        cv_id=other_user_cv.id,
        job_description="Other user's job description",
        content_hash="other_hash",
        company="Other Co",
        role="Other Role",
        score=80,
    )
    db_session.add(a)
    db_session.commit()
    return a


class TestGetAnalysisByIdOwnership:
    def test_returns_analysis_when_owner_matches(self, db_session, test_user, other_user_analysis):
        # test_user is NOT the owner of other_user_analysis — should return None
        result = get_analysis_by_id(
            db_session,
            str(other_user_analysis.id),
            user_id=test_user.id,
        )
        assert result is None

    def test_returns_analysis_for_correct_owner(self, db_session, other_user, other_user_analysis):
        result = get_analysis_by_id(
            db_session,
            str(other_user_analysis.id),
            user_id=other_user.id,
        )
        assert result is not None
        assert result.id == other_user_analysis.id

    def test_no_user_id_bypasses_check(self, db_session, other_user_analysis):
        """user_id=None preserves legacy behavior for trusted internal callers."""
        result = get_analysis_by_id(db_session, str(other_user_analysis.id))
        assert result is not None
        assert result.id == other_user_analysis.id

    def test_invalid_uuid_returns_none(self, db_session, test_user):
        assert get_analysis_by_id(db_session, "not-a-uuid", user_id=test_user.id) is None

    def test_missing_id_returns_none(self, db_session, test_user):
        assert get_analysis_by_id(db_session, str(uuid.uuid4()), user_id=test_user.id) is None

    def test_user_with_no_cvs_cannot_access_any_analysis(self, db_session, other_user_analysis):
        """A user that has never uploaded a CV must not see any analysis."""
        lonely_user = User(id=uuid.uuid4(), email="lonely@example.com", password_hash="$2b$12$x")
        db_session.add(lonely_user)
        db_session.commit()

        result = get_analysis_by_id(
            db_session,
            str(other_user_analysis.id),
            user_id=lonely_user.id,
        )
        assert result is None
