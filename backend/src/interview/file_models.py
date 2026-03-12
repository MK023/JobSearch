"""Interview file attachment model."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..database.base import Base


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
}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
PRESIGNED_URL_EXPIRY_SECONDS = 600  # 10 minutes


class InterviewFile(Base):
    __tablename__ = "interview_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    interview_id = Column(
        UUID(as_uuid=True),
        ForeignKey("interviews.id", ondelete="CASCADE"),
        nullable=False,
    )

    # File metadata
    original_filename = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=False)
    file_size = Column(Integer, nullable=True)  # Set after upload confirmation
    r2_key = Column(String(500), nullable=False, unique=True)  # R2 object key

    # Status tracking
    status = Column(String(20), nullable=False, default=FileStatus.PENDING)
    scan_result = Column(String(2000), nullable=True)  # Claude API scan summary

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    interview = relationship("Interview", back_populates="files")

    __table_args__ = (
        Index("idx_interview_files_interview_id", "interview_id"),
        Index("idx_interview_files_status", "status"),
    )
