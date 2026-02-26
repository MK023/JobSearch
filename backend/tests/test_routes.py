"""Tests for HTTP routes using FastAPI TestClient."""

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

    with patch("src.main.lifespan", _test_lifespan):
        app = create_app()
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
