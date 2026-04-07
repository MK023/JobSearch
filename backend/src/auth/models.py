"""User model for authentication."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..database.base import Base

# Lockout policy
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 30


class User(Base):
    """Application user with email/password authentication."""

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )

    # Brute-force protection
    failed_login_attempts = Column(Integer, default=0)
    locked_until = Column(DateTime(timezone=True), nullable=True)

    cv_profiles = relationship("CVProfile", back_populates="user", cascade="all, delete-orphan")

    @property
    def is_locked(self) -> bool:
        """Check if the account is currently locked out."""
        if not self.locked_until:
            return False
        now = datetime.now(UTC)
        lock = self.locked_until
        # SQLite returns naive datetimes; normalize for comparison
        if lock.tzinfo is None:
            lock = lock.replace(tzinfo=UTC)
        return bool(now < lock)
