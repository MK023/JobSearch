"""SQLAlchemy model for app_preferences."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database.base import Base


class AppPreference(Base):
    """Generic key-value row for persisted runtime settings.

    Writes are whitelisted server-side (see preferences.service.ALLOWED_KEYS).
    Reads are cached in-memory per-process; the cache is invalidated on set.
    """

    __tablename__ = "app_preferences"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover — debug only
        return f"<AppPreference {self.key}={self.value!r}>"

    @property
    def typed_value(self) -> Any:
        """Convenience accessor; value is already typed by JSON column."""
        return self.value
