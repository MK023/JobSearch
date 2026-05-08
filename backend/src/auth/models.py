"""User model for authentication."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database.base import Base

if TYPE_CHECKING:
    from ..cv.models import CVProfile

# Lockout policy
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 30


class User(Base):
    """Application user with email/password authentication."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )

    # Brute-force protection
    failed_login_attempts: Mapped[int | None] = mapped_column(default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    cv_profiles: Mapped[list["CVProfile"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    @property
    def is_locked(self) -> bool:
        """Check if the account is currently locked out."""
        lock = self.locked_until
        if lock is None:
            return False
        now = datetime.now(UTC)
        # SQLite returns naive datetimes; normalize for comparison
        if lock.tzinfo is None:
            lock = lock.replace(tzinfo=UTC)
        return bool(now < lock)
