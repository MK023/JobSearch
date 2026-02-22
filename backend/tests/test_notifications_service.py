"""Tests for notification service."""

import uuid

from src.notifications.models import NotificationLog
from src.notifications.service import _already_notified, decrypt_value, encrypt_value


class TestEncryptDecrypt:
    def test_roundtrip(self):
        plaintext = "my-secret-smtp-password"
        encrypted = encrypt_value(plaintext)
        assert encrypted != plaintext
        assert decrypt_value(encrypted) == plaintext

    def test_different_values_produce_different_ciphertexts(self):
        a = encrypt_value("password1")
        b = encrypt_value("password2")
        assert a != b

    def test_encrypted_starts_with_gAAAAA(self):
        encrypted = encrypt_value("test")
        assert encrypted.startswith("gAAAAA")


class TestAlreadyNotified:
    def test_returns_false_when_not_notified(self, db_session, test_analysis):
        result = _already_notified(db_session, test_analysis.id, "followup_reminder")
        assert result is False

    def test_returns_true_when_already_notified(self, db_session, test_analysis):
        log = NotificationLog(
            analysis_id=test_analysis.id,
            notification_type="followup_reminder",
            recipient="test@example.com",
            subject="Test",
        )
        db_session.add(log)
        db_session.commit()

        result = _already_notified(db_session, test_analysis.id, "followup_reminder")
        assert result is True

    def test_different_type_not_matched(self, db_session, test_analysis):
        log = NotificationLog(
            analysis_id=test_analysis.id,
            notification_type="other_type",
            recipient="test@example.com",
        )
        db_session.add(log)
        db_session.commit()

        result = _already_notified(db_session, test_analysis.id, "followup_reminder")
        assert result is False

    def test_different_analysis_not_matched(self, db_session, test_analysis):
        log = NotificationLog(
            analysis_id=test_analysis.id,
            notification_type="followup_reminder",
            recipient="test@example.com",
        )
        db_session.add(log)
        db_session.commit()

        other_id = uuid.uuid4()
        result = _already_notified(db_session, other_id, "followup_reminder")
        assert result is False
