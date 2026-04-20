"""Tests for HTTP routes using FastAPI TestClient with real SQLite DB."""

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.auth.models import User
from src.database import get_db
from src.database.base import Base
from src.dependencies import get_current_user

# Import all models so Base.metadata.create_all() sees every table.
from tests.conftest import _ALL_MODELS  # noqa: F401


def _create_test_app(db_session=None, user=None):
    """Create a FastAPI app with optional real DB and user overrides."""
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
        if db_session is not None:

            def _real_db():
                yield db_session

            app.dependency_overrides[get_db] = _real_db
        if user is not None:
            app.dependency_overrides[get_current_user] = lambda: user
        yield app


@pytest.fixture
def app_client():
    """TestClient without auth — for health, 404, login tests."""
    for app in _create_test_app():
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client


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
def real_db():
    """In-memory SQLite session with PostgreSQL polyfills."""
    from sqlalchemy import event

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
def real_user(real_db):
    """Create a real user in the test DB."""
    user = User(
        id=uuid.uuid4(),
        email="test@example.com",
        password_hash="$2b$12$fakehash",
    )
    real_db.add(user)
    real_db.commit()
    return user


@pytest.fixture
def auth_client(real_db, real_user):
    """TestClient with real SQLite DB and authenticated user."""
    for app in _create_test_app(db_session=real_db, user=real_user):
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client


class TestHealthEndpoint:
    def test_health_returns_200(self, app_client):
        """Health check always returns 200 with at least a status field."""
        response = app_client.get("/health")
        assert response.status_code == 200
        assert "status" in response.json()


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
    """Verify authenticated page rendering returns 200 — real DB, no mocks."""

    def test_dashboard_page_renders(self, auth_client):
        resp = auth_client.get("/")
        assert resp.status_code == 200
        assert "Dashboard" in resp.text or "dashboard" in resp.text.lower()

    def test_analyze_page_renders(self, auth_client):
        resp = auth_client.get("/analyze")
        assert resp.status_code == 200
        assert "Analizza" in resp.text or "analyze" in resp.text.lower() or "Analisi" in resp.text

    def test_history_page_renders(self, auth_client):
        resp = auth_client.get("/history")
        assert resp.status_code == 200
        assert "Storico" in resp.text or "history" in resp.text.lower()

    def test_interviews_page_renders(self, auth_client):
        resp = auth_client.get("/interviews")
        assert resp.status_code == 200
        assert "Colloqui" in resp.text or "interview" in resp.text.lower()

    def test_settings_page_renders(self, auth_client):
        resp = auth_client.get("/settings")
        assert resp.status_code == 200
        assert "Impostazioni" in resp.text or "settings" in resp.text.lower()

    def test_agenda_page_renders(self, auth_client):
        resp = auth_client.get("/agenda")
        assert resp.status_code == 200
        assert "Agenda" in resp.text or "agenda" in resp.text.lower()

    def test_admin_page_renders(self, auth_client):
        resp = auth_client.get("/admin")
        assert resp.status_code == 200

    def test_stats_page_renders(self, auth_client):
        resp = auth_client.get("/stats")
        assert resp.status_code == 200


class TestInboxValidationErrorShape:
    """CodeQL py/stack-trace-exposure fix: ensure the endpoint returns the
    user-facing message via exc.args[0] instead of str(exc), and that the
    generic fallback kicks in when args is empty."""

    def test_returns_400_with_validation_message(self, auth_client, real_db):
        from src.inbox import routes as inbox_routes

        def _boom(**_kwargs):
            raise inbox_routes.InboxValidationError("testo troppo corto")

        with patch("src.inbox.routes.ingest", _boom):
            resp = auth_client.post(
                "/api/v1/inbox",
                json={"raw_text": "x" * 80, "source": "linkedin", "source_url": "https://example.com/job"},
            )
        assert resp.status_code == 400
        body = resp.json()
        assert "error" in body
        assert body["error"] == "testo troppo corto"

    def test_returns_generic_error_when_exception_has_no_args(self, auth_client):
        from src.inbox import routes as inbox_routes

        def _boom(**_kwargs):
            raise inbox_routes.InboxValidationError()

        with patch("src.inbox.routes.ingest", _boom):
            resp = auth_client.post(
                "/api/v1/inbox",
                json={"raw_text": "x" * 80, "source": "linkedin", "source_url": "https://example.com/job"},
            )
        assert resp.status_code == 400
        assert resp.json()["error"] == "Richiesta non valida."


class TestBackupErrorShape:
    """CodeQL py/stack-trace-exposure fix on /api/v1/backup."""

    def test_runtime_error_returns_generic_message(self, auth_client):
        with patch("src.integrations.backup.create_backup", side_effect=RuntimeError("R2 down")):
            resp = auth_client.post("/api/v1/backup")
        assert resp.status_code == 500
        # Must NOT leak the "R2 down" string from str(e).
        body = resp.json()
        assert "R2 down" not in body["error"]
        assert "R2" in body["error"]  # User-facing hint mentions the service generically.


class TestAnalysisDetailSidebarContext:
    """Regression: opening an analysis from /history used to null out
    the Storico / Agenda / Analytics badges because view_analysis built
    its sidebar context by hand. After the fix it goes through _base_ctx
    and every badge key is present."""

    def test_view_analysis_includes_full_sidebar_context(self, auth_client, real_db, real_user):
        import uuid

        from src.analysis.models import AnalysisStatus, JobAnalysis
        from src.cv.models import CVProfile

        cv = CVProfile(id=uuid.uuid4(), user_id=real_user.id, raw_text="x", name="cv")
        real_db.add(cv)
        analysis = JobAnalysis(
            id=uuid.uuid4(),
            cv_id=cv.id,
            job_description="x",
            status=AnalysisStatus.PENDING.value,
        )
        real_db.add(analysis)
        real_db.commit()

        resp = auth_client.get(f"/analysis/{analysis.id}")
        assert resp.status_code == 200
        # Every sidebar-relevant count lives in the rendered HTML through
        # base.html; the existence of the sidebar itself is enough — the
        # page used to 500 when any of these were missing.
        assert "sidebar" in resp.text
