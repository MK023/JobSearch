"""CV profile model."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..database.base import Base


class CVProfile(Base):
    """User's CV stored as raw text, used as input for all AI analyses."""

    __tablename__ = "cv_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    raw_text = Column(Text, nullable=False)
    name = Column(String(255), default="")
    # Livello CEFR di inglese dichiarato dall'utente (A1..C2/Native, vuoto se
    # non specificato). Normalizzato via ``normalize_cefr_token`` lato service
    # — il DB tiene la stringa raw così evitiamo CHECK constraint che
    # bloccherebbero le migrazioni storiche.
    english_level = Column(String(8), nullable=True, default="")
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    user = relationship("User", back_populates="cv_profiles")
    analyses = relationship("JobAnalysis", back_populates="cv", cascade="all, delete-orphan")
