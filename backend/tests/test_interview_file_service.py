"""Tests for interview file service (DB operations)."""

from datetime import UTC, datetime

from src.interview.file_models import FileStatus
from src.interview.file_service import (
    confirm_upload,
    count_files_for_interview,
    create_file_record,
    delete_file_record,
    get_file_by_id,
    get_interview_by_id,
    get_not_compiled_files,
    update_scan_result,
)
from src.interview.service import InterviewScheduleData, create_or_update_interview


class TestCreateFileRecord:
    def test_creates_pending_file(self, db_session, test_analysis):
        interview = create_or_update_interview(
            db_session,
            test_analysis.id,
            InterviewScheduleData(scheduled_at=datetime(2026, 3, 15, 10, 0, tzinfo=UTC)),
        )
        db_session.flush()

        file = create_file_record(
            db_session,
            interview_id=interview.id,
            original_filename="doc.pdf",
            content_type="application/pdf",
            r2_key="interviews/abc/123.pdf",
        )

        assert file.id is not None
        assert file.status == FileStatus.PENDING
        assert file.original_filename == "doc.pdf"
        assert file.file_size is None


class TestConfirmUpload:
    def test_confirms_and_sets_size(self, db_session, test_analysis):
        interview = create_or_update_interview(
            db_session,
            test_analysis.id,
            InterviewScheduleData(scheduled_at=datetime(2026, 3, 15, 10, 0, tzinfo=UTC)),
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

        confirm_upload(db_session, file, 54321)

        assert file.status == FileStatus.UPLOADED
        assert file.file_size == 54321


class TestUpdateScanResult:
    def test_updates_status_and_result(self, db_session, test_analysis):
        interview = create_or_update_interview(
            db_session,
            test_analysis.id,
            InterviewScheduleData(scheduled_at=datetime(2026, 3, 15, 10, 0, tzinfo=UTC)),
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

        update_scan_result(db_session, file, FileStatus.COMPILED, "Il documento risulta compilato.")

        assert file.status == FileStatus.COMPILED
        assert file.scan_result == "Il documento risulta compilato."


class TestGetNotCompiledFiles:
    def test_returns_not_compiled_files(self, db_session, test_analysis):
        interview = create_or_update_interview(
            db_session,
            test_analysis.id,
            InterviewScheduleData(scheduled_at=datetime(2026, 3, 15, 10, 0, tzinfo=UTC)),
        )
        db_session.flush()

        file = create_file_record(
            db_session,
            interview_id=interview.id,
            original_filename="doc.pdf",
            content_type="application/pdf",
            r2_key="interviews/abc/123.pdf",
        )
        file.status = FileStatus.NOT_COMPILED  # type: ignore[assignment]
        db_session.flush()

        not_compiled = get_not_compiled_files(db_session)
        assert len(not_compiled) == 1


class TestCountFiles:
    def test_counts_correctly(self, db_session, test_analysis):
        interview = create_or_update_interview(
            db_session,
            test_analysis.id,
            InterviewScheduleData(scheduled_at=datetime(2026, 3, 15, 10, 0, tzinfo=UTC)),
        )
        db_session.flush()

        for i in range(3):
            create_file_record(
                db_session,
                interview_id=interview.id,
                original_filename=f"doc{i}.pdf",
                content_type="application/pdf",
                r2_key=f"interviews/abc/{i}.pdf",
            )
        db_session.flush()

        assert count_files_for_interview(db_session, interview.id) == 3


class TestDeleteFileRecord:
    def test_deletes_file(self, db_session, test_analysis):
        interview = create_or_update_interview(
            db_session,
            test_analysis.id,
            InterviewScheduleData(scheduled_at=datetime(2026, 3, 15, 10, 0, tzinfo=UTC)),
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
        file_id = file.id

        delete_file_record(db_session, file)
        db_session.flush()

        assert get_file_by_id(db_session, file_id) is None


class TestGetInterviewById:
    def test_returns_interview(self, db_session, test_analysis):
        interview = create_or_update_interview(
            db_session,
            test_analysis.id,
            InterviewScheduleData(scheduled_at=datetime(2026, 3, 15, 10, 0, tzinfo=UTC)),
        )
        db_session.flush()

        found = get_interview_by_id(db_session, interview.id)
        assert found is not None
        assert found.id == interview.id

    def test_returns_none_for_missing(self, db_session):
        import uuid

        found = get_interview_by_id(db_session, uuid.uuid4())
        assert found is None
