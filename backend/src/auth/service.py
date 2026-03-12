"""Authentication service: user management, password hashing, session handling."""

from typing import cast as type_cast

import bcrypt
from sqlalchemy.orm import Session

from ..config import settings
from .models import User


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
    """Verify credentials and return user, or None if invalid."""
    user = get_user_by_email(db, email)
    if not user or not verify_password(password, type_cast(str, user.password_hash)):
        return None
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
