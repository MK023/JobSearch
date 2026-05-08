"""Batch analysis models — persistent queue for job analysis."""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    cv_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cv_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Job data (option B: full JD stored for retry)
    job_description: Mapped[str] = mapped_column(Text, nullable=False)
    job_url: Mapped[str | None] = mapped_column(String(500), default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model: Mapped[str | None] = mapped_column(String(20), default="haiku")

    # Processing state — SQLEnum kept here (vs the String(20) convention used
    # elsewhere) because the column was created with the Postgres enum type
    # and a values-roundtrip would need an Alembic migration. Out of scope
    # for the typing-only PR5a.
    status: Mapped[BatchItemStatus] = mapped_column(
        SQLEnum(BatchItemStatus, values_callable=lambda e: [s.value for s in e]),
        default=BatchItemStatus.PENDING,
        nullable=False,
    )
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("job_analyses.id", ondelete="SET NULL"),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int | None] = mapped_column(default=0)

    # Preview (for status display without re-reading JD)
    preview: Mapped[str | None] = mapped_column(String(100), default="")

    # Origin of the batch entry — propagated end-to-end so that the
    # resulting JobAnalysis row carries the caller's source. Without this,
    # any non-manual batch ingestion (notably the Cowork MCP workflow)
    # silently degraded to ``manual`` and the dashboard widgets that
    # filter by source missed the rows.
    source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)

    # Timestamps
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        Index("idx_batch_items_batch_status", "batch_id", "status"),
        Index("idx_batch_items_content_hash_model", "content_hash", "model"),
    )
