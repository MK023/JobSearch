"""Tests for authentication service."""

from src.auth.service import (
    authenticate_user,
    get_user_by_email,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_and_verify(self):
        password = "test_password_123"
        hashed = hash_password(password)
        assert hashed != password
        assert verify_password(password, hashed)

    def test_wrong_password_fails(self):
        hashed = hash_password("correct_password")
        assert not verify_password("wrong_password", hashed)


class TestGetUserByEmail:
    def test_finds_existing_user(self, db_session, test_user):
        user = get_user_by_email(db_session, "test@example.com")
        assert user is not None
        assert user.id == test_user.id

    def test_returns_none_for_unknown(self, db_session):
        user = get_user_by_email(db_session, "unknown@example.com")
        assert user is None


class TestAuthenticateUser:
    def test_valid_credentials(self, db_session):
        from src.auth.models import User

        hashed = hash_password("mypassword")
        user = User(email="auth@test.com", password_hash=hashed)
        db_session.add(user)
        db_session.commit()

        result = authenticate_user(db_session, "auth@test.com", "mypassword")
        assert result is not None
        assert result.email == "auth@test.com"

    def test_wrong_password(self, db_session):
        from src.auth.models import User

        hashed = hash_password("mypassword")
        user = User(email="auth2@test.com", password_hash=hashed)
        db_session.add(user)
        db_session.commit()

        result = authenticate_user(db_session, "auth2@test.com", "wrongpassword")
        assert result is None

    def test_nonexistent_user(self, db_session):
        result = authenticate_user(db_session, "nobody@test.com", "password")
        assert result is None
