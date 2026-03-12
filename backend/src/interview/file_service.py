"""Interview file service - database operations for file attachments."""

import logging
from uuid import UUID

from sqlalchemy.orm import Session

from .file_models import FileStatus, InterviewFile
from .models import Interview

logger = logging.getLogger(__name__)

# Max files per interview
MAX_FILES_PER_INTERVIEW = 10


def get_interview_by_id(db: Session, interview_id: UUID | str) -> Interview | None:
    """Get interview by its own ID (not analysis_id)."""
    return db.query(Interview).filter(Interview.id == interview_id).first()


def create_file_record(
    db: Session,
    *,
    interview_id: UUID | str,
    original_filename: str,
    content_type: str,
    r2_key: str,
) -> InterviewFile:
    """Create a new file record with PENDING status."""
    file = InterviewFile(
        interview_id=interview_id,
        original_filename=original_filename,
        content_type=content_type,
        r2_key=r2_key,
        status=FileStatus.PENDING,
    )
    db.add(file)
    db.flush()
    return file


def get_file_by_id(db: Session, file_id: UUID | str) -> InterviewFile | None:
    """Get a file record by ID."""
    return db.query(InterviewFile).filter(InterviewFile.id == file_id).first()


def get_files_for_interview(db: Session, interview_id: UUID | str) -> list[InterviewFile]:
    """Get all files for an interview, ordered by creation date."""
    return (
        db.query(InterviewFile)
        .filter(InterviewFile.interview_id == interview_id)
        .order_by(InterviewFile.created_at.asc())
        .all()
    )


def count_files_for_interview(db: Session, interview_id: UUID | str) -> int:
    """Count files for an interview."""
    return db.query(InterviewFile).filter(InterviewFile.interview_id == interview_id).count()


def confirm_upload(db: Session, file: InterviewFile, file_size: int) -> None:
    """Mark file as uploaded after R2 HEAD check confirms it exists."""
    file.status = FileStatus.UPLOADED  # type: ignore[assignment]
    file.file_size = file_size  # type: ignore[assignment]
    db.flush()


def update_scan_result(
    db: Session,
    file: InterviewFile,
    status: str,
    scan_result: str,
) -> None:
    """Update file status after Claude API scan."""
    file.status = status  # type: ignore[assignment]
    file.scan_result = scan_result  # type: ignore[assignment]
    db.flush()


def delete_file_record(db: Session, file: InterviewFile) -> None:
    """Delete a file record from the database."""
    db.delete(file)
    db.flush()


def get_unscanned_files(db: Session) -> list[InterviewFile]:
    """Get all files with 'uploaded' status that haven't been scanned yet."""
    return (
        db.query(InterviewFile)
        .filter(InterviewFile.status == FileStatus.UPLOADED)
        .order_by(InterviewFile.created_at.asc())
        .all()
    )


def get_not_compiled_files(db: Session) -> list[InterviewFile]:
    """Get all files with 'not_compiled' status (for reminder emails)."""
    return (
        db.query(InterviewFile)
        .filter(InterviewFile.status == FileStatus.NOT_COMPILED)
        .order_by(InterviewFile.created_at.asc())
        .all()
    )
