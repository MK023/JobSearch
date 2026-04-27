"""Tests for the dashboard snapshot endpoint and cache.

The snapshot powers homepage live updates: each call returns a dict of
``{widget_key: pre_rendered_html}`` so the client can swap one ``<section>``
at a time when an SSE event fires. We assert all nine widget keys are
present, the cache TTL absorbs back-to-back calls, and unauthenticated
clients are rejected.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.auth.models import User
from src.dashboard import snapshot as snapshot_mod
from src.database import get_db
from src.database.base import Base
from src.dependencies import get_current_user

# Ensure all models are registered with Base.metadata.
from tests.conftest import _ALL_MODELS  # noqa: F401


def _sqlite_date_trunc(part, value):
    """SQLite polyfill for PostgreSQL's date_trunc()."""
    if value is None:
        return None
    fmt = {"hour": "%Y-%m-%d %H:00:00", "day": "%Y-%m-%d", "month": "%Y-%m-01"}.get(part, "%Y-%m-%d")
    from datetime import datetime as _dt

    if isinstance(value, str):
        value = _dt.fromisoformat(value)
    return value.strftime(fmt)


@pytest.fixture
def _real_db():
    """In-memory SQLite session with PostgreSQL polyfills."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _register_functions(dbapi_conn, _rec):
        dbapi_conn.create_function("date_trunc", 2, _sqlite_date_trunc)

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def _user(_real_db):
    user = User(id=uuid.uuid4(), email="test@example.com", password_hash="$2b$12$fake")
    _real_db.add(user)
    _real_db.commit()
    return user


@pytest.fixture
def auth_client(_real_db, _user):
    """TestClient with real SQLite DB and authenticated user."""
    from src.main import create_app

    @asynccontextmanager
    async def _test_lifespan(app):
        from src.integrations.cache import NullCacheService

        app.state.cache = NullCacheService()
        yield

    def _db():
        yield _real_db

    with patch("src.main.lifespan", _test_lifespan), patch("src.main.settings") as s:
        s.trusted_hosts_list = ["*"]
        s.cors_origins_list = ["*"]
        s.cors_allow_credentials = True
        s.secret_key = "test-secret"
        app = create_app()
        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = lambda: _user
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client


@pytest.fixture
def app_client():
    """Unauthenticated TestClient — exercises the auth gate."""
    from src.main import create_app

    @asynccontextmanager
    async def _test_lifespan(app):
        from src.integrations.cache import NullCacheService

        app.state.cache = NullCacheService()
        yield

    with patch("src.main.lifespan", _test_lifespan), patch("src.main.settings") as s:
        s.trusted_hosts_list = ["*"]
        s.cors_origins_list = ["*"]
        s.cors_allow_credentials = True
        s.secret_key = "test-secret"
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client


class TestDashboardSnapshotEndpoint:
    def test_requires_auth(self, app_client):
        resp = app_client.get("/api/v1/dashboard/snapshot", follow_redirects=False)
        # Auth gate either redirects (browser flow) or 401s (API flow);
        # either is acceptable as long as it isn't 200.
        assert resp.status_code in (303, 401, 403)

    def test_returns_all_nine_widgets(self, auth_client):
        snapshot_mod.invalidate_cache()
        resp = auth_client.get("/api/v1/dashboard/snapshot")
        assert resp.status_code == 200
        data = resp.json()
        expected = {
            "followup",
            "interviews",
            "pending_cowork",
            "activity_today",
            "top_candidates",
            "inbox",
            "news",
            "todos",
            "db_usage",
        }
        assert set(data.keys()) == expected

    def test_widget_html_contains_data_widget_attribute(self, auth_client):
        """Every partial wraps its <section> with data-widget="<key>" so the
        client can target the swap. If a partial drops the attribute, the
        client-side patch becomes a no-op — guard against that here."""
        snapshot_mod.invalidate_cache()
        resp = auth_client.get("/api/v1/dashboard/snapshot")
        data = resp.json()
        for key, html in data.items():
            assert isinstance(html, str)
            assert f'data-widget="{key}"' in html, f"widget '{key}' missing data-widget attribute"


class TestSnapshotCache:
    def test_ttl_absorbs_back_to_back_calls(self, auth_client):
        """Two consecutive calls within the TTL return identical objects —
        the second one is served from the cache, not recomputed."""
        snapshot_mod.invalidate_cache()
        first = auth_client.get("/api/v1/dashboard/snapshot").json()
        second = auth_client.get("/api/v1/dashboard/snapshot").json()
        assert first == second

    def test_invalidate_resets_cache_slot(self, auth_client):
        """``invalidate_cache()`` is the test hatch — after it the cache
        slot is reset and the next request must repopulate it."""
        snapshot_mod.invalidate_cache()
        auth_client.get("/api/v1/dashboard/snapshot")
        assert snapshot_mod._cache["value"] is not None  # populated

        snapshot_mod.invalidate_cache()
        assert snapshot_mod._cache["value"] is None
        assert snapshot_mod._cache["expires_at"] == 0.0
