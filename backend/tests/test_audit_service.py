"""Tests for audit service."""

from unittest.mock import MagicMock

from src.audit.models import AuditLog
from src.audit.service import audit
from src.rate_limit import get_client_ip


class TestGetIp:
    def test_extracts_x_forwarded_for(self):
        request = MagicMock()
        request.headers = {"X-Forwarded-For": "1.2.3.4, 10.0.0.1"}
        assert get_client_ip(request) == "1.2.3.4"

    def test_ignores_x_real_ip(self):
        """X-Real-IP is not trusted — it can be spoofed to bypass rate limits."""
        request = MagicMock()
        request.headers = {"X-Real-IP": "5.6.7.8"}
        request.client.host = "10.0.0.1"
        assert get_client_ip(request) == "10.0.0.1"

    def test_xff_single_ip(self):
        request = MagicMock()
        request.headers = {"X-Forwarded-For": "1.2.3.4"}
        assert get_client_ip(request) == "1.2.3.4"

    def test_uses_client_host(self):
        request = MagicMock()
        request.headers = {}
        request.client.host = "10.0.0.1"
        assert get_client_ip(request) == "10.0.0.1"

    def test_returns_empty_when_no_client(self):
        request = MagicMock()
        request.headers = {}
        request.client = None
        assert get_client_ip(request) == "unknown"


class TestAudit:
    def test_creates_audit_log(self, db_session, test_user):
        request = MagicMock()
        request.headers = {"X-Forwarded-For": "192.168.1.1"}
        request.session = {"user_id": str(test_user.id)}

        audit(db_session, request, "test_action", "some detail")
        db_session.commit()

        logs = db_session.query(AuditLog).all()
        assert len(logs) == 1
        assert logs[0].action == "test_action"
        assert logs[0].detail == "some detail"
        assert logs[0].ip_address == "192.168.1.1"
        assert logs[0].user_id == test_user.id

    def test_creates_log_with_explicit_user_id(self, db_session, test_user):
        request = MagicMock()
        request.headers = {}
        request.client.host = "127.0.0.1"
        request.session = {}

        audit(db_session, request, "login", "email=test", user_id=test_user.id)
        db_session.commit()

        logs = db_session.query(AuditLog).all()
        assert len(logs) == 1
        assert logs[0].user_id == test_user.id

    def test_creates_log_without_user(self, db_session):
        request = MagicMock()
        request.headers = {}
        request.client.host = "127.0.0.1"
        request.session = {}

        audit(db_session, request, "anonymous_action")
        db_session.commit()

        logs = db_session.query(AuditLog).all()
        assert len(logs) == 1
        assert logs[0].user_id is None
        assert logs[0].action == "anonymous_action"
