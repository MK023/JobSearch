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

    def test_payload_shape(self, client):
        r = client.get("/health").json()
        assert r["status"] in ("ok", "degraded")
        assert "db" in r
        assert "version" in r
        assert "uptime_seconds" in r
        assert "cache" in r

    def test_db_size_mb_field_present(self, client):
        """db_size_mb is always returned. Null on SQLite (test env), float on Postgres."""
        r = client.get("/health").json()
        assert "db_size_mb" in r
        # SQLite (test env) does not support pg_database_size → null
        assert r["db_size_mb"] is None or isinstance(r["db_size_mb"], int | float)
