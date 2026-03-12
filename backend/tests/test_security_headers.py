"""Tests for security headers and middleware."""

from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.main import create_app


@pytest.fixture
def client():
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
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


class TestSecurityHeaders:
    def test_csp_header_present(self, client):
        response = client.get("/health")
        assert "Content-Security-Policy" in response.headers
        csp = response.headers["Content-Security-Policy"]
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    def test_nosniff_header(self, client):
        response = client.get("/health")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"

    def test_referrer_policy(self, client):
        response = client.get("/health")
        assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_permissions_policy(self, client):
        response = client.get("/health")
        assert "Permissions-Policy" in response.headers

    def test_no_deprecated_xss_protection(self, client):
        response = client.get("/health")
        assert "X-XSS-Protection" not in response.headers
