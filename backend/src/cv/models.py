"""CV profile model."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database.base import Base

if TYPE_CHECKING:
    from ..analysis.models import JobAnalysis
    from ..auth.models import User


class CVProfile(Base):
    """User's CV stored as raw text, used as input for all AI analyses."""

    __tablename__ = "cv_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), default="")
    # Livello CEFR di inglese dichiarato dall'utente (A1..C2/Native, vuoto se
    # non specificato). Normalizzato via ``normalize_cefr_token`` lato service
    # — il DB tiene la stringa raw così evitiamo CHECK constraint che
    # bloccherebbero le migrazioni storiche.
    english_level: Mapped[str | None] = mapped_column(String(8), nullable=True, default="")
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    user: Mapped["User"] = relationship(back_populates="cv_profiles")
    analyses: Mapped[list["JobAnalysis"]] = relationship(
        back_populates="cv",
        cascade="all, delete-orphan",
    )
