"""Tests for the /health endpoint."""

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
        mock_settings.secret_key = "test-secret"  # noqa: S105
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


class TestHealthEndpoint:
    def test_returns_200(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_minimal_payload_when_unauthenticated(self, client):
        """Unauthenticated health check returns only status (no system info leak)."""
        r = client.get("/health").json()
        assert r["status"] in ("ok", "degraded")
        assert "db" not in r
        assert "version" not in r
        assert "uptime_seconds" not in r
