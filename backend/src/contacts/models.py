"""Recruiter contact model."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..database.base import Base


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id = Column(
        UUID(as_uuid=True),
        ForeignKey("job_analyses.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name = Column(String(255), default="")
    email = Column(String(255), default="")
    phone = Column(String(50), default="")
    company = Column(String(255), default="")
    linkedin_url = Column(String(500), default="")
    notes = Column(Text, default="")
    source = Column(String(20), default="manual")
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )

    analysis = relationship("JobAnalysis", back_populates="contacts")
