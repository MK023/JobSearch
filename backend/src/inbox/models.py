"""Inbox models — raw paste ingestion from Chrome extension."""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID

from ..database.base import Base


class InboxStatus(enum.StrEnum):
    """Lifecycle of an inbox item from ingestion to analysis resolution."""

    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"
    SKIPPED = "skipped"  # e.g., content_hash dedup hit — linked to existing analysis


class InboxSource(enum.StrEnum):
    """Known origin site for the pasted content."""

    LINKEDIN = "linkedin"
    INDEED = "indeed"
    INFOJOBS = "infojobs"
    WTTJ = "wttj"  # welcometothejungle.com
    REMOTE_OK = "remote_ok"
    MANUAL = "manual"
    OTHER = "other"


class InboxItem(Base):
    """Raw job paste from the Chrome extension awaiting or post-analysis."""

    __tablename__ = "inbox_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )
    source_url = Column(String(500), default="", nullable=False)
    source = Column(String(20), default=InboxSource.MANUAL.value, nullable=False)
    raw_text = Column(Text, nullable=False)
    content_hash = Column(String(64), default="", nullable=False, index=True)
    status = Column(
        String(20),
        default=InboxStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    analysis_id = Column(
        UUID(as_uuid=True),
        ForeignKey("job_analyses.id", ondelete="SET NULL"),
        nullable=True,
    )
    error_message = Column(Text, nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("idx_inbox_user_status", "user_id", "status"),)
