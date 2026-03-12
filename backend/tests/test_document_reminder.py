"""Tests for document reminder service (Resend integration)."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from src.interview.file_models import FileStatus, InterviewFile
from src.interview.service import create_or_update_interview
from src.notifications.document_reminder import (
    _build_document_reminder_html,
    _build_plain_text,
    send_document_reminders,
)
from src.notifications.models import NotificationLog


class TestBuildDocumentReminderHtml:
    def test_contains_file_info(self):
        file = MagicMock()
        file.original_filename = "modulo.pdf"
        file.scan_result = "Template vuoto"

        html = _build_document_reminder_html([file], "TestCorp", "Developer")
        assert "modulo.pdf" in html
        assert "Template vuoto" in html
        assert "TestCorp" in html
        assert "Developer" in html

    def test_escapes_html_entities(self):
        file = MagicMock()
        file.original_filename = "test&file.pdf"
        file.scan_result = "Test"

        html = _build_document_reminder_html([file], "A&B Corp", "Dev")
        assert "A&amp;B Corp" in html
        assert "test&amp;file.pdf" in html


class TestBuildPlainText:
    def test_contains_file_info(self):
        file = MagicMock()
        file.original_filename = "modulo.pdf"
        file.scan_result = "Non compilato"

        text = _build_plain_text([file], "TestCorp", "Developer")
        assert "modulo.pdf" in text
        assert "TestCorp" in text
        assert "Developer" in text


class TestSendDocumentReminders:
    @patch("src.notifications.document_reminder.settings")
    def test_skips_when_not_configured(self, mock_settings, db_session):
        mock_settings.resend_api_key = ""
        mock_settings.document_reminder_email = ""

        result = send_document_reminders(db_session)
        assert result == 0

    @patch("src.notifications.document_reminder.resend")
    @patch("src.notifications.document_reminder.settings")
    def test_sends_reminder_for_not_compiled_files(self, mock_settings, mock_resend, db_session, test_analysis):
        mock_settings.resend_api_key = "re_test_key"
        mock_settings.document_reminder_email = "test@example.com"
        mock_settings.resend_from_email = "noreply@test.com"

        # Create interview + file
        interview = create_or_update_interview(
            db_session, test_analysis.id, scheduled_at=datetime(2026, 3, 20, 10, 0, tzinfo=UTC)
        )
        db_session.flush()

        file = InterviewFile(
            interview_id=interview.id,
            original_filename="modulo.pdf",
            content_type="application/pdf",
            r2_key="interviews/abc/123.pdf",
            status=FileStatus.NOT_COMPILED,
            scan_result="Template vuoto",
        )
        db_session.add(file)
        db_session.flush()

        result = send_document_reminders(db_session)
        assert result == 1
        mock_resend.Emails.send.assert_called_once()

        # Check notification log was created
        log = (
            db_session.query(NotificationLog)
            .filter(NotificationLog.notification_type == f"document_reminder:{file.id}")
            .first()
        )
        assert log is not None
        assert log.recipient == "test@example.com"

    @patch("src.notifications.document_reminder.resend")
    @patch("src.notifications.document_reminder.settings")
    def test_skips_already_notified_files(self, mock_settings, mock_resend, db_session, test_analysis):
        mock_settings.resend_api_key = "re_test_key"
        mock_settings.document_reminder_email = "test@example.com"
        mock_settings.resend_from_email = "noreply@test.com"

        interview = create_or_update_interview(
            db_session, test_analysis.id, scheduled_at=datetime(2026, 3, 20, 10, 0, tzinfo=UTC)
        )
        db_session.flush()

        file = InterviewFile(
            interview_id=interview.id,
            original_filename="modulo.pdf",
            content_type="application/pdf",
            r2_key="interviews/abc/123.pdf",
            status=FileStatus.NOT_COMPILED,
            scan_result="Template vuoto",
        )
        db_session.add(file)
        db_session.flush()

        # Pre-create notification log
        db_session.add(
            NotificationLog(
                analysis_id=test_analysis.id,
                notification_type=f"document_reminder:{file.id}",
                recipient="test@example.com",
                subject="Test",
            )
        )
        db_session.flush()

        result = send_document_reminders(db_session)
        assert result == 0
        mock_resend.Emails.send.assert_not_called()
