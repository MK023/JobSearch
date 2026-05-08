"""Interview file attachment model."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database.base import Base

if TYPE_CHECKING:
    from .models import Interview


class FileStatus:
    """File status constants."""

    PENDING = "pending"  # Presigned URL generated, not yet uploaded
    UPLOADED = "uploaded"  # Upload confirmed via HEAD check
    COMPILED = "compiled"  # Claude API scan: document is filled
    NOT_COMPILED = "not_compiled"  # Claude API scan: document is empty/unfilled
    SCAN_ERROR = "scan_error"  # Claude API scan failed


VALID_FILE_STATUSES = {
    FileStatus.PENDING,
    FileStatus.UPLOADED,
    FileStatus.COMPILED,
    FileStatus.NOT_COMPILED,
    FileStatus.SCAN_ERROR,
}

# Allowed MIME types and max file size
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/msword",  # .doc
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
    "application/vnd.ms-excel",  # .xls
    "text/plain",  # .txt
}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
PRESIGNED_URL_EXPIRY_SECONDS = 600  # 10 minutes


class InterviewFile(Base):
    """File attachment for an interview, stored in Cloudflare R2."""

    __tablename__ = "interview_files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    interview_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interviews.id", ondelete="CASCADE"),
        nullable=False,
    )

    # File metadata
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int | None] = mapped_column(nullable=True)  # Set after upload confirmation
    r2_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)  # R2 object key

    # Status tracking
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=FileStatus.PENDING)
    scan_result: Mapped[str | None] = mapped_column(String(2000), nullable=True)  # Claude API scan summary

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    interview: Mapped["Interview"] = relationship(back_populates="files")

    __table_args__ = (
        Index("idx_interview_files_interview_id", "interview_id"),
        Index("idx_interview_files_status", "status"),
    )
