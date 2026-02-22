"""Tests for CV service."""

from src.cv.service import get_latest_cv, save_cv


class TestSaveCV:
    def test_creates_new_cv(self, db_session, test_user):
        cv = save_cv(db_session, test_user.id, "My CV text content for testing purposes.", "John Doe")
        db_session.commit()
        assert cv.raw_text == "My CV text content for testing purposes."
        assert cv.name == "John Doe"
        assert cv.user_id == test_user.id

    def test_updates_existing_cv(self, db_session, test_user):
        save_cv(db_session, test_user.id, "Original CV content for testing.", "V1")
        db_session.commit()

        cv = save_cv(db_session, test_user.id, "Updated CV content for testing.", "V2")
        db_session.commit()

        assert cv.raw_text == "Updated CV content for testing."
        assert cv.name == "V2"


class TestGetLatestCV:
    def test_returns_cv_for_user(self, db_session, test_user, test_cv):
        result = get_latest_cv(db_session, test_user.id)
        assert result is not None
        assert result.id == test_cv.id

    def test_returns_none_for_unknown_user(self, db_session):
        import uuid

        result = get_latest_cv(db_session, uuid.uuid4())
        assert result is None
