"""Tests for InterviewFile model."""

import uuid
from datetime import UTC, datetime

from src.interview.file_models import (
    ALLOWED_CONTENT_TYPES,
    MAX_FILE_SIZE_BYTES,
    VALID_FILE_STATUSES,
    FileStatus,
    InterviewFile,
)
from src.interview.service import create_or_update_interview


class TestInterviewFileModel:
    def test_create_file_record(self, db_session, test_analysis):
        scheduled = datetime(2026, 3, 15, 10, 0, tzinfo=UTC)
        interview = create_or_update_interview(db_session, test_analysis.id, scheduled_at=scheduled)
        db_session.flush()

        file = InterviewFile(
            interview_id=interview.id,
            original_filename="document.pdf",
            content_type="application/pdf",
            r2_key=f"interviews/{interview.id}/{uuid.uuid4()}.pdf",
            status=FileStatus.PENDING,
        )
        db_session.add(file)
        db_session.flush()

        assert file.id is not None
        assert file.status == "pending"
        assert file.original_filename == "document.pdf"

    def test_file_belongs_to_interview(self, db_session, test_analysis):
        scheduled = datetime(2026, 3, 15, 10, 0, tzinfo=UTC)
        interview = create_or_update_interview(db_session, test_analysis.id, scheduled_at=scheduled)
        db_session.flush()

        file = InterviewFile(
            interview_id=interview.id,
            original_filename="test.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            r2_key=f"interviews/{interview.id}/{uuid.uuid4()}.docx",
        )
        db_session.add(file)
        db_session.flush()

        # Reload interview to check relationship
        db_session.refresh(interview)
        assert len(interview.files) == 1
        assert interview.files[0].original_filename == "test.docx"

    def test_cascade_delete(self, db_session, test_analysis):
        """Deleting an interview should delete its files."""
        scheduled = datetime(2026, 3, 15, 10, 0, tzinfo=UTC)
        interview = create_or_update_interview(db_session, test_analysis.id, scheduled_at=scheduled)
        db_session.flush()

        file = InterviewFile(
            interview_id=interview.id,
            original_filename="doc.pdf",
            content_type="application/pdf",
            r2_key=f"interviews/{interview.id}/{uuid.uuid4()}.pdf",
        )
        db_session.add(file)
        db_session.flush()

        file_id = file.id
        db_session.delete(interview)
        db_session.flush()

        assert db_session.query(InterviewFile).filter_by(id=file_id).first() is None

    def test_file_statuses(self):
        assert FileStatus.PENDING == "pending"
        assert FileStatus.UPLOADED == "uploaded"
        assert FileStatus.COMPILED == "compiled"
        assert FileStatus.NOT_COMPILED == "not_compiled"
        assert FileStatus.SCAN_ERROR == "scan_error"
        assert len(VALID_FILE_STATUSES) == 5

    def test_allowed_content_types(self):
        assert "application/pdf" in ALLOWED_CONTENT_TYPES
        assert "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in ALLOWED_CONTENT_TYPES
        assert "image/png" not in ALLOWED_CONTENT_TYPES

    def test_max_file_size(self):
        assert MAX_FILE_SIZE_BYTES == 10 * 1024 * 1024
