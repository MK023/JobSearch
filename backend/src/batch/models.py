"""Batch analysis models — persistent queue for job analysis."""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID

from ..database.base import Base


class BatchItemStatus(enum.StrEnum):
    """Lifecycle of a single batch item."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    SKIPPED = "skipped"  # dedup: already analyzed
    ERROR = "error"


class BatchItem(Base):
    """Persistent batch queue item — survives server restarts."""

    __tablename__ = "batch_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id = Column(String(36), nullable=False, index=True)
    cv_id = Column(
        UUID(as_uuid=True),
        ForeignKey("cv_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Job data (option B: full JD stored for retry)
    job_description = Column(Text, nullable=False)
    job_url = Column(String(500), default="")
    content_hash = Column(String(64), nullable=False, index=True)
    model = Column(String(20), default="haiku")

    # Processing state
    status: Column[str] = Column(
        SQLEnum(BatchItemStatus, values_callable=lambda e: [s.value for s in e]),
        default=BatchItemStatus.PENDING,
        nullable=False,
    )
    analysis_id = Column(UUID(as_uuid=True), ForeignKey("job_analyses.id", ondelete="SET NULL"), nullable=True)
    error_message = Column(Text, nullable=True)
    attempt_count = Column(Integer, default=0)

    # Preview (for status display without re-reading JD)
    preview = Column(String(100), default="")

    # Origin of the batch entry — propagated end-to-end so that the
    # resulting JobAnalysis row carries the caller's source. Without this,
    # any non-manual batch ingestion (notably the Cowork MCP workflow)
    # silently degraded to ``manual`` and the dashboard widgets that
    # filter by source missed the rows.
    source = Column(String(20), default="manual", nullable=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    __table_args__ = (
        Index("idx_batch_items_batch_status", "batch_id", "status"),
        Index("idx_batch_items_content_hash_model", "content_hash", "model"),
    )
