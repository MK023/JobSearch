"""Interview scheduling model."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..database.base import Base

# Ensure InterviewFile is importable (relationship target)
from .file_models import InterviewFile  # noqa: F401


class Interview(Base):
    __tablename__ = "interviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id = Column(
        UUID(as_uuid=True),
        ForeignKey("job_analyses.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    scheduled_at = Column(DateTime(timezone=True), nullable=False)
    ends_at = Column(DateTime(timezone=True), nullable=True)
    platform = Column(String(20), nullable=True)  # google_meet, teams, zoom, phone, in_person, other
    interview_type = Column(String(20), nullable=True)  # tecnico, hr, conoscitivo, finale, other
    interviewer_name = Column(String(255), nullable=True)
    recruiter_name = Column(String(255), nullable=True)
    recruiter_email = Column(String(255), nullable=True)
    meeting_link = Column(String(500), nullable=True)
    meeting_id = Column(String(100), nullable=True)
    phone_number = Column(String(50), nullable=True)
    access_pin = Column(String(20), nullable=True)
    location = Column(String(500), nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    analysis = relationship("JobAnalysis", back_populates="interview")
    files = relationship("InterviewFile", back_populates="interview", cascade="all, delete-orphan")

    __table_args__ = (Index("idx_interviews_scheduled", "scheduled_at"),)
