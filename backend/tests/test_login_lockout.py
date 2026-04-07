"""Tests for brute-force login lockout protection."""

from datetime import UTC, datetime, timedelta

from src.auth.models import LOCKOUT_MINUTES, MAX_FAILED_ATTEMPTS, User
from src.auth.service import authenticate_user, hash_password


class TestAccountLockout:
    """Verify brute-force protection on the login flow."""

    def _create_user(self, db_session: object) -> User:
        user = User(
            email="locktest@example.com",
            password_hash=hash_password("correct-password"),
        )
        db_session.add(user)  # type: ignore[union-attr]
        db_session.commit()  # type: ignore[union-attr]
        return user

    def test_successful_login_resets_counter(self, db_session):
        user = self._create_user(db_session)
        user.failed_login_attempts = 3  # type: ignore[assignment]
        db_session.commit()

        result = authenticate_user(db_session, "locktest@example.com", "correct-password")
        assert result is not None
        assert user.failed_login_attempts == 0
        assert user.locked_until is None

    def test_failed_login_increments_counter(self, db_session):
        self._create_user(db_session)

        authenticate_user(db_session, "locktest@example.com", "wrong")
        db_session.commit()

        user = db_session.query(User).filter(User.email == "locktest@example.com").first()
        assert user.failed_login_attempts == 1

    def test_account_locks_after_max_attempts(self, db_session):
        self._create_user(db_session)

        for _ in range(MAX_FAILED_ATTEMPTS):
            authenticate_user(db_session, "locktest@example.com", "wrong")
            db_session.commit()

        user = db_session.query(User).filter(User.email == "locktest@example.com").first()
        assert user.failed_login_attempts == MAX_FAILED_ATTEMPTS
        assert user.locked_until is not None
        assert user.is_locked is True

    def test_locked_account_rejects_correct_password(self, db_session):
        user = self._create_user(db_session)
        user.locked_until = datetime.now(UTC) + timedelta(minutes=LOCKOUT_MINUTES)  # type: ignore[assignment]
        db_session.commit()

        result = authenticate_user(db_session, "locktest@example.com", "correct-password")
        assert result is None

    def test_expired_lockout_allows_login(self, db_session):
        user = self._create_user(db_session)
        user.failed_login_attempts = MAX_FAILED_ATTEMPTS  # type: ignore[assignment]
        user.locked_until = datetime.now(UTC) - timedelta(minutes=1)  # type: ignore[assignment]
        db_session.commit()

        result = authenticate_user(db_session, "locktest@example.com", "correct-password")
        assert result is not None
        assert user.failed_login_attempts == 0

    def test_nonexistent_user_does_not_crash(self, db_session):
        """Timing-safe: must not reveal whether user exists."""
        result = authenticate_user(db_session, "noone@example.com", "anything")
        assert result is None

    def test_lockout_duration_is_correct(self, db_session):
        self._create_user(db_session)

        for _ in range(MAX_FAILED_ATTEMPTS):
            authenticate_user(db_session, "locktest@example.com", "wrong")
            db_session.commit()

        user = db_session.query(User).filter(User.email == "locktest@example.com").first()
        expected_unlock = datetime.now(UTC) + timedelta(minutes=LOCKOUT_MINUTES)
        lock = user.locked_until
        # SQLite returns naive datetimes
        if lock.tzinfo is None:
            lock = lock.replace(tzinfo=UTC)
        assert abs((lock - expected_unlock).total_seconds()) < 5
