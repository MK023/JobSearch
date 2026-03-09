"""Tests for read-only API routes."""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def auth_client():
    """Create a TestClient with authentication and DB mocked."""
    from contextlib import asynccontextmanager

    from src.auth.models import User
    from src.database import get_db
    from src.dependencies import get_current_user
    from src.main import create_app

    fake_user = MagicMock(spec=User)
    fake_user.id = uuid.uuid4()
    fake_user.email = "test@example.com"
    fake_user.is_active = True

    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
    mock_session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

    @asynccontextmanager
    async def _test_lifespan(app):
        from src.integrations.cache import NullCacheService

        app.state.cache = NullCacheService()
        yield

    def _fake_db():
        yield mock_session

    with patch("src.main.lifespan", _test_lifespan), patch("src.main.settings") as mock_settings:
        mock_settings.trusted_hosts_list = ["*"]
        mock_settings.cors_origins_list = ["*"]
        mock_settings.cors_allow_credentials = True
        mock_settings.secret_key = "test-secret"
        app = create_app()
        app.dependency_overrides[get_current_user] = lambda: fake_user
        app.dependency_overrides[get_db] = _fake_db
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client


class TestCandidatureEndpoints:
    @patch("src.read_routes.get_candidature", return_value=[])
    def test_list_candidature(self, _mock, auth_client):
        resp = auth_client.get("/api/v1/candidature")
        assert resp.status_code == 200
        assert "candidature" in resp.json()

    @patch("src.read_routes.get_candidature", return_value=[])
    def test_list_candidature_with_status(self, _mock, auth_client):
        resp = auth_client.get("/api/v1/candidature?status=candidato")
        assert resp.status_code == 200

    @patch("src.read_routes.search_candidature", return_value=[])
    def test_search_candidature(self, _mock, auth_client):
        resp = auth_client.get("/api/v1/candidature/search?q=google")
        assert resp.status_code == 200
        assert "candidature" in resp.json()

    def test_search_candidature_requires_query(self, auth_client):
        resp = auth_client.get("/api/v1/candidature/search")
        assert resp.status_code == 422

    @patch("src.read_routes.get_top_candidature", return_value=[])
    def test_top_candidature(self, _mock, auth_client):
        resp = auth_client.get("/api/v1/candidature/top")
        assert resp.status_code == 200

    @patch("src.read_routes.get_candidature_by_date_range", return_value=[])
    def test_date_range(self, _mock, auth_client):
        resp = auth_client.get("/api/v1/candidature/date-range?date_from=2026-01-01&date_to=2026-12-31")
        assert resp.status_code == 200

    def test_date_range_invalid_format(self, auth_client):
        resp = auth_client.get("/api/v1/candidature/date-range?date_from=bad&date_to=bad")
        assert resp.status_code == 400

    @patch("src.read_routes.get_stale_candidature", return_value=[])
    def test_stale_candidature(self, _mock, auth_client):
        resp = auth_client.get("/api/v1/candidature/stale")
        assert resp.status_code == 200

    @patch("src.read_routes.get_stale_candidature", return_value=[])
    def test_stale_with_days_param(self, _mock, auth_client):
        resp = auth_client.get("/api/v1/candidature/stale?days=14")
        assert resp.status_code == 200


class TestCandidatureDetail:
    @patch("src.read_routes.get_analysis_by_id", return_value=None)
    def test_not_found(self, _mock, auth_client):
        fake_id = str(uuid.uuid4())
        resp = auth_client.get(f"/api/v1/candidature/{fake_id}")
        assert resp.status_code == 404


class TestInterviewPrep:
    @patch("src.read_routes.get_analysis_by_id", return_value=None)
    def test_not_found(self, _mock, auth_client):
        fake_id = str(uuid.uuid4())
        resp = auth_client.get(f"/api/v1/interview-prep/{fake_id}")
        assert resp.status_code == 404


class TestCoverLetters:
    @patch("src.read_routes.get_analysis_by_id", return_value=None)
    def test_not_found(self, _mock, auth_client):
        fake_id = str(uuid.uuid4())
        resp = auth_client.get(f"/api/v1/cover-letters/{fake_id}")
        assert resp.status_code == 404


class TestContactsSearch:
    @patch("src.read_routes.search_all_contacts", return_value=[])
    def test_search_contacts(self, _mock, auth_client):
        resp = auth_client.get("/api/v1/contacts/search?q=marco")
        assert resp.status_code == 200
        assert "contacts" in resp.json()

    def test_search_requires_query(self, auth_client):
        resp = auth_client.get("/api/v1/contacts/search")
        assert resp.status_code == 422


class TestFollowups:
    @patch("src.read_routes.get_followup_alerts", return_value=[])
    def test_pending_followups(self, _mock, auth_client):
        resp = auth_client.get("/api/v1/followups/pending")
        assert resp.status_code == 200
        assert "pending_followups" in resp.json()


class TestActivitySummary:
    @patch("src.read_routes.get_upcoming_interviews", return_value=[])
    @patch("src.read_routes.get_spending", return_value={})
    @patch("src.read_routes.get_dashboard", return_value={})
    @patch("src.read_routes.get_candidature_by_date_range", return_value=[])
    def test_activity_summary(self, _c, _d, _s, _i, auth_client):
        resp = auth_client.get("/api/v1/activity-summary?days=7")
        assert resp.status_code == 200
        data = resp.json()
        assert "period_days" in data
        assert data["new_candidature"] == 0
        assert data["avg_score"] == 0


class TestInterviewsUpcoming:
    @patch("src.interview.routes.get_upcoming_interviews", return_value=[])
    def test_with_days_param(self, _mock, auth_client):
        resp = auth_client.get("/api/v1/interviews-upcoming?days=7")
        assert resp.status_code == 200

    @patch("src.interview.routes.get_upcoming_interviews", return_value=[])
    def test_without_days_param(self, _mock, auth_client):
        resp = auth_client.get("/api/v1/interviews-upcoming")
        assert resp.status_code == 200
