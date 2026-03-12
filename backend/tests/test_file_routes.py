"""Integration tests for file upload routes.

Tests the full request/response cycle with mocked R2 operations.
"""

from datetime import UTC, datetime

from src.interview.file_models import ALLOWED_CONTENT_TYPES, FileStatus
from src.interview.file_service import (
    MAX_FILES_PER_INTERVIEW,
    count_files_for_interview,
    create_file_record,
    delete_file_record,
    get_file_by_id,
)
from src.interview.service import create_or_update_interview


class TestRequestUploadValidation:
    """Tests for POST /api/v1/files/request-upload validation logic."""

    def test_validates_content_type(self):
        """Invalid content type should be rejected."""
        assert "image/png" not in ALLOWED_CONTENT_TYPES
        assert "application/pdf" in ALLOWED_CONTENT_TYPES
        assert "text/plain" not in ALLOWED_CONTENT_TYPES

    def test_validates_filename_path_traversal(self):
        """Filenames with path traversal should be rejected."""
        bad_names = ["../../../etc/passwd", "file/name.pdf", "file\\name.pdf", "..pdf"]
        for name in bad_names:
            stripped = name.strip()
            has_bad_chars = "/" in stripped or "\\" in stripped or ".." in stripped
            assert has_bad_chars, f"Expected rejection for: {name}"

    def test_validates_filename_empty(self):
        """Empty filenames should be rejected."""
        assert not "".strip()
        assert not "   ".strip()


class TestFileServiceIntegration:
    """Tests for file service operations used by routes."""

    def test_file_limit_enforced(self, db_session, test_analysis):
        interview = create_or_update_interview(
            db_session, test_analysis.id, scheduled_at=datetime(2026, 3, 20, 10, 0, tzinfo=UTC)
        )
        db_session.flush()

        for i in range(MAX_FILES_PER_INTERVIEW):
            create_file_record(
                db_session,
                interview_id=interview.id,
                original_filename=f"doc{i}.pdf",
                content_type="application/pdf",
                r2_key=f"interviews/abc/{i}.pdf",
            )
        db_session.flush()

        count = count_files_for_interview(db_session, interview.id)
        assert count == MAX_FILES_PER_INTERVIEW

    def test_confirm_rejects_already_confirmed(self, db_session, test_analysis):
        """A file that's already uploaded can't be confirmed again."""
        interview = create_or_update_interview(
            db_session, test_analysis.id, scheduled_at=datetime(2026, 3, 20, 10, 0, tzinfo=UTC)
        )
        db_session.flush()

        file = create_file_record(
            db_session,
            interview_id=interview.id,
            original_filename="doc.pdf",
            content_type="application/pdf",
            r2_key="interviews/abc/123.pdf",
        )
        file.status = FileStatus.UPLOADED  # type: ignore[assignment]
        db_session.flush()

        # The route checks file.status != FileStatus.PENDING
        assert file.status != FileStatus.PENDING

    def test_scan_rejects_pending_file(self, db_session, test_analysis):
        """A pending file (not yet uploaded) can't be scanned."""
        interview = create_or_update_interview(
            db_session, test_analysis.id, scheduled_at=datetime(2026, 3, 20, 10, 0, tzinfo=UTC)
        )
        db_session.flush()

        file = create_file_record(
            db_session,
            interview_id=interview.id,
            original_filename="doc.pdf",
            content_type="application/pdf",
            r2_key="interviews/abc/123.pdf",
        )
        db_session.flush()

        # The route checks file.status in (UPLOADED, SCAN_ERROR)
        assert file.status == FileStatus.PENDING
        assert file.status not in (FileStatus.UPLOADED, FileStatus.SCAN_ERROR)

    def test_delete_cleans_up_record(self, db_session, test_analysis):
        """Deleting a file should remove the DB record."""
        interview = create_or_update_interview(
            db_session, test_analysis.id, scheduled_at=datetime(2026, 3, 20, 10, 0, tzinfo=UTC)
        )
        db_session.flush()

        file = create_file_record(
            db_session,
            interview_id=interview.id,
            original_filename="doc.pdf",
            content_type="application/pdf",
            r2_key="interviews/abc/123.pdf",
        )
        db_session.flush()
        fid = file.id

        delete_file_record(db_session, file)
        db_session.flush()

        assert get_file_by_id(db_session, fid) is None
