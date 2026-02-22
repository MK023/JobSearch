"""Notification tracking model."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID

from ..database.base import Base


class NotificationLog(Base):
    """Tracks sent notifications to avoid duplicates."""

    __tablename__ = "notification_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id = Column(
        UUID(as_uuid=True),
        ForeignKey("job_analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    notification_type = Column(String(50), nullable=False)  # "followup_reminder"
    recipient = Column(String(255), nullable=False)
    subject = Column(String(500), default="")
    detail = Column(Text, default="")
    sent_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
