"""Authentication service: user management, password hashing, session handling."""

import secrets
from datetime import UTC, datetime, timedelta
from typing import cast as type_cast

import bcrypt
from sqlalchemy.orm import Session

from ..config import settings
from .models import LOCKOUT_MINUTES, MAX_FAILED_ATTEMPTS, User

# Process-local dummy bcrypt hash generated at import time from fresh random
# bytes, used for constant-time login when the email is unknown. Both the
# input (random bytes, never a literal) and the salt are unique per worker
# boot — nothing here is a credential that could be leaked or reused.
_DUMMY_HASH = bcrypt.hashpw(secrets.token_bytes(32), bcrypt.gensalt()).decode()


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Check a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def get_user_by_email(db: Session, email: str) -> User | None:
    """Look up a user by email address."""
    return db.query(User).filter(User.email == email).first()


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    """Verify credentials with brute-force protection.

    - Returns None if credentials are invalid or account is locked.
    - Increments failed_login_attempts on failure.
    - Locks account after MAX_FAILED_ATTEMPTS for LOCKOUT_MINUTES.
    - Resets counter on successful login.
    - Uses constant-time comparison even when user is not found.
    """
    user = get_user_by_email(db, email)

    if not user:
        # Timing-safe: always run bcrypt even if user doesn't exist,
        # so attacker can't distinguish "user not found" from "wrong password".
        verify_password(password, _DUMMY_HASH)
        return None

    # Check lockout
    if user.is_locked:
        return None

    if not verify_password(password, type_cast(str, user.password_hash)):
        # Increment failed attempts
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1  # type: ignore[assignment]
        if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
            user.locked_until = datetime.now(UTC) + timedelta(minutes=LOCKOUT_MINUTES)  # type: ignore[assignment]
        db.flush()
        return None

    # Success: reset lockout state
    user.failed_login_attempts = 0  # type: ignore[assignment]
    user.locked_until = None  # type: ignore[assignment]
    db.flush()
    return user


def ensure_admin_user(db: Session) -> None:
    """Create admin user from env vars if it doesn't exist yet."""
    if not settings.admin_email or not settings.admin_password:
        return

    existing = get_user_by_email(db, settings.admin_email)
    if existing:
        return

    admin = User(
        email=settings.admin_email,
        password_hash=hash_password(settings.admin_password),
    )
    db.add(admin)
    db.flush()
