"""Tests for HTTP routes using FastAPI TestClient."""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client():
    """Create a TestClient with patched lifespan to skip DB migrations and external services."""
    from contextlib import asynccontextmanager

    from src.main import create_app

    @asynccontextmanager
    async def _test_lifespan(app):
        from src.integrations.cache import NullCacheService

        app.state.cache = NullCacheService()
        yield

    with patch("src.main.lifespan", _test_lifespan), patch("src.main.settings") as mock_settings:
        mock_settings.trusted_hosts_list = ["*"]
        mock_settings.cors_origins_list = ["*"]
        mock_settings.cors_allow_credentials = True
        mock_settings.secret_key = "test-secret"
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client


@pytest.fixture
def auth_client():
    """Create a TestClient with authentication and DB mocked — pages render without hitting DB."""
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
    # Provide a chainable query mock for any direct db.query(...) calls
    mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

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


class TestHealthEndpoint:
    def test_health_returns_ok(self, app_client):
        with patch("src.main.get_db") as mock_get_db:
            mock_session = MagicMock()
            mock_get_db.return_value = iter([mock_session])
            response = app_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("ok", "degraded")
        assert "version" in data
        assert "uptime_seconds" in data
        assert "db" in data


class TestErrorPages:
    def test_404_returns_html(self, app_client):
        response = app_client.get("/nonexistent-page-that-does-not-exist")
        assert response.status_code == 404
        assert "404" in response.text

    def test_login_page_accessible(self, app_client):
        response = app_client.get("/login")
        assert response.status_code == 200
        assert "Job Search" in response.text

    def test_404_contains_dashboard_link(self, app_client):
        response = app_client.get("/nonexistent-page-that-does-not-exist")
        assert response.status_code == 404
        assert "/dashboard" in response.text


class TestAuthRoutes:
    def test_login_page_get(self, app_client):
        response = app_client.get("/login")
        assert response.status_code == 200
        assert "Accedi" in response.text

    def test_login_wrong_credentials(self, app_client):
        with patch("src.auth.routes.authenticate_user", return_value=None), patch("src.auth.routes.audit"):
            response = app_client.post(
                "/login",
                data={"email": "wrong@test.com", "password": "wrong"},
                follow_redirects=False,
            )
        assert response.status_code == 401

    def test_root_redirects_to_login(self, app_client):
        response = app_client.get("/", follow_redirects=False)
        assert response.status_code == 303
        assert "/login" in response.headers.get("location", "")


class TestPageRoutesRequireAuth:
    """All page routes must redirect unauthenticated users to /login."""

    def test_analyze_page_requires_auth(self, app_client):
        resp = app_client.get("/analyze", follow_redirects=False)
        assert resp.status_code == 303
        assert "/login" in resp.headers["location"]

    def test_history_page_requires_auth(self, app_client):
        resp = app_client.get("/history", follow_redirects=False)
        assert resp.status_code == 303
        assert "/login" in resp.headers["location"]

    def test_interviews_page_requires_auth(self, app_client):
        resp = app_client.get("/interviews", follow_redirects=False)
        assert resp.status_code == 303
        assert "/login" in resp.headers["location"]

    def test_settings_page_requires_auth(self, app_client):
        resp = app_client.get("/settings", follow_redirects=False)
        assert resp.status_code == 303
        assert "/login" in resp.headers["location"]

    def test_dashboard_page_requires_auth(self, app_client):
        resp = app_client.get("/", follow_redirects=False)
        assert resp.status_code == 303
        assert "/login" in resp.headers["location"]


class TestAuthenticatedPages:
    """Verify authenticated page rendering returns 200 and expected content."""

    @patch(
        "src.pages.get_spending",
        return_value=MagicMock(
            total_analysis=0.0,
            total_cover_letter=0.0,
            budget=5.0,
            remaining=5.0,
        ),
    )
    @patch("src.pages.get_upcoming_interviews", return_value=[])
    @patch("src.pages.get_followup_alerts", return_value=[])
    @patch("src.pages.get_recent_analyses", return_value=[])
    @patch(
        "src.pages.get_dashboard",
        return_value=MagicMock(
            total_analyses=0,
            total_candidato=0,
            total_colloquio=0,
            total_scartato=0,
        ),
    )
    def test_dashboard_page_renders(self, _d, _a, _f, _u, _s, auth_client):
        resp = auth_client.get("/")
        assert resp.status_code == 200
        assert "Dashboard" in resp.text or "dashboard" in resp.text.lower()

    @patch(
        "src.pages.get_spending",
        return_value=MagicMock(
            total_analysis=0.0,
            total_cover_letter=0.0,
            budget=5.0,
            remaining=5.0,
        ),
    )
    @patch("src.pages.get_latest_cv", return_value=None)
    @patch("src.batch.service.get_batch_status", return_value=[])
    def test_analyze_page_renders(self, _b, _cv, _s, auth_client):
        resp = auth_client.get("/analyze")
        assert resp.status_code == 200
        assert "Analizza" in resp.text or "analyze" in resp.text.lower() or "Analisi" in resp.text

    @patch("src.pages.get_recent_analyses", return_value=[])
    def test_history_page_renders(self, _a, auth_client):
        resp = auth_client.get("/history")
        assert resp.status_code == 200
        assert "Storico" in resp.text or "history" in resp.text.lower()

    @patch("src.pages.get_upcoming_interviews", return_value=[])
    def test_interviews_page_renders(self, _u, auth_client):
        resp = auth_client.get("/interviews")
        assert resp.status_code == 200
        assert "Colloqui" in resp.text or "interview" in resp.text.lower()

    @patch(
        "src.pages.get_spending",
        return_value=MagicMock(
            total_analysis=0.0,
            total_cover_letter=0.0,
            budget=5.0,
            remaining=5.0,
        ),
    )
    @patch("src.pages.get_latest_cv", return_value=None)
    def test_settings_page_renders(self, _cv, _s, auth_client):
        resp = auth_client.get("/settings")
        assert resp.status_code == 200
        assert "Impostazioni" in resp.text or "settings" in resp.text.lower()
