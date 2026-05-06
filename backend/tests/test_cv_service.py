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


class TestSaveCVEnglishLevel:
    """``english_level`` viene salvato normalizzato via ``normalize_cefr_token``.

    Token validi (A1..C2/Native, anche lowercase) sono persistiti come canonici;
    sinonimi mappati al CEFR; tutto il resto degrada a "" senza errori.
    """

    def test_default_empty_when_omitted(self, db_session, test_user):
        cv = save_cv(db_session, test_user.id, "CV text content here.", "John")
        db_session.commit()
        assert cv.english_level == ""

    def test_canonical_cefr_preserved(self, db_session, test_user):
        cv = save_cv(db_session, test_user.id, "CV text body for B2 user.", "John", english_level="B2")
        db_session.commit()
        assert cv.english_level == "B2"

    def test_lowercase_normalized(self, db_session, test_user):
        cv = save_cv(db_session, test_user.id, "CV text body lowercase.", "John", english_level="c1")
        db_session.commit()
        assert cv.english_level == "C1"

    def test_synonym_madrelingua_to_native(self, db_session, test_user):
        cv = save_cv(db_session, test_user.id, "CV text body native.", "John", english_level="madrelingua")
        db_session.commit()
        assert cv.english_level == "Native"

    def test_unknown_token_degraded_to_empty(self, db_session, test_user):
        cv = save_cv(db_session, test_user.id, "CV text body.", "John", english_level="banana")
        db_session.commit()
        assert cv.english_level == ""

    def test_update_overwrites_english_level(self, db_session, test_user):
        save_cv(db_session, test_user.id, "First CV body content here.", "V1", english_level="B1")
        db_session.commit()
        cv = save_cv(db_session, test_user.id, "Second CV body content here.", "V2", english_level="C1")
        db_session.commit()
        assert cv.english_level == "C1"


class TestGetLatestCV:
    def test_returns_cv_for_user(self, db_session, test_user, test_cv):
        result = get_latest_cv(db_session, test_user.id)
        assert result is not None
        assert result.id == test_cv.id

    def test_returns_none_for_unknown_user(self, db_session):
        import uuid

        result = get_latest_cv(db_session, uuid.uuid4())
        assert result is None
