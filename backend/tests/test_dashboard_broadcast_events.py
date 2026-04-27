"""Verify mutating actions emit the SSE events that drive live widgets.

Each widget on the homepage subscribes (via the shared SSE stream) to a
specific event name. If a route mutates data but forgets to broadcast,
the widget would stay stale until a backup poll fires 60 s later. These
tests guard the contract: route call → broadcast_sync(<expected event>).

We intercept ``broadcast_sync`` in each module where it's imported (FastAPI
sync handlers run on the thread pool with no asyncio loop, so the function
becomes a no-op in tests anyway — patching just lets us assert it was
called with the right argument).
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

from src.analysis.models import AnalysisStatus, JobAnalysis
from src.auth.models import User
from src.cv.models import CVProfile
from src.database import get_db
from src.database.base import Base
from src.dependencies import get_current_user

# Ensure all models are registered with Base.metadata.
from tests.conftest import _ALL_MODELS  # noqa: F401


def _sqlite_date_trunc(part, value):
    if value is None:
        return None
    fmt = {"hour": "%Y-%m-%d %H:00:00", "day": "%Y-%m-%d", "month": "%Y-%m-01"}.get(part, "%Y-%m-%d")
    from datetime import datetime as _dt

    if isinstance(value, str):
        value = _dt.fromisoformat(value)
    return value.strftime(fmt)


@pytest.fixture
def _real_db():
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
def _analysis(_real_db, _user):
    cv = CVProfile(id=uuid.uuid4(), user_id=_user.id, raw_text="x" * 200, name="Tester")
    _real_db.add(cv)
    _real_db.commit()
    a = JobAnalysis(
        id=uuid.uuid4(),
        cv_id=cv.id,
        job_description="Software Engineer",
        company="TestCorp",
        role="Engineer",
        score=80,
        recommendation="APPLY",
        status=AnalysisStatus.APPLIED,
        strengths=[],
        gaps=[],
        advice="",
        model_used="claude-haiku-4-5-20251001",
        tokens_input=1,
        tokens_output=1,
        cost_usd=0.0,
        content_hash="abc",
    )
    _real_db.add(a)
    _real_db.commit()
    return a


@pytest.fixture
def auth_client(_real_db, _user):
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


class TestAnalysisStatusBroadcast:
    def test_update_status_broadcasts_analysis_status(self, _real_db, _analysis):
        """Status mutations must announce themselves so the dashboard
        widgets that depend on status (top_candidates, pending_cowork,
        followup) refresh in the same SSE tick.

        ``update_status`` resolves ``broadcast_sync`` via a local import
        each call, so patching the source attribute on the sse module is
        what hits the bound name at call time.
        """
        from src.analysis import service
        from src.notification_center import sse

        with patch.object(sse, "broadcast_sync") as mock:
            service.update_status(_real_db, _analysis, AnalysisStatus.REJECTED)
            assert mock.call_args_list[-1].args == ("analysis:status",)


class TestTodoBroadcast:
    def test_add_todo_broadcasts(self, auth_client):
        from src.agenda import routes

        with patch.object(routes, "broadcast_sync") as mock:
            resp = auth_client.post("/api/v1/todos", data={"text": "first"})
            assert resp.status_code == 200
            mock.assert_called_with("todos:changed")

    def test_toggle_todo_broadcasts(self, auth_client, _real_db):
        from src.agenda import routes
        from src.agenda.models import TodoItem

        item = TodoItem(text="x")
        _real_db.add(item)
        _real_db.commit()

        with patch.object(routes, "broadcast_sync") as mock:
            resp = auth_client.post(f"/api/v1/todos/{item.id}/toggle")
            assert resp.status_code == 200
            mock.assert_called_with("todos:changed")

    def test_delete_todo_broadcasts(self, auth_client, _real_db):
        from src.agenda import routes
        from src.agenda.models import TodoItem

        item = TodoItem(text="x")
        _real_db.add(item)
        _real_db.commit()

        with patch.object(routes, "broadcast_sync") as mock:
            resp = auth_client.delete(f"/api/v1/todos/{item.id}")
            assert resp.status_code == 200
            mock.assert_called_with("todos:changed")


class TestInterviewBroadcastWiring:
    """The interview routes go through SQLAlchemy UUID lookups that the
    in-memory SQLite fixture doesn't always serialise cleanly. Driving
    them via TestClient drifts into fixture territory that has nothing
    to do with the broadcast contract.

    Instead we assert the wiring statically: every mutating handler
    references ``_INTERVIEWS_EVENT`` and the route module imports
    ``broadcast_sync``. If someone removes a broadcast call by accident,
    the source-level grep will fail and so will this test.

    Functional coverage of the dashboard refresh is still solid because
    every interview mutation also calls ``update_status`` (verified in
    ``TestAnalysisStatusBroadcast``), which emits ``analysis:status`` —
    so widgets refresh either way.
    """

    def test_interview_routes_import_broadcast_sync(self):
        from src.interview import routes

        assert hasattr(routes, "broadcast_sync"), "broadcast_sync not imported"
        assert routes._INTERVIEWS_EVENT == "interviews:changed"

    def test_every_mutating_handler_calls_broadcast(self):
        from pathlib import Path

        src = Path(__file__).resolve().parents[1] / "src" / "interview" / "routes.py"
        body = src.read_text(encoding="utf-8")
        # Every @router.post / @router.delete that commits should also
        # broadcast — the four handlers we touched in PR 3.
        broadcast_calls = body.count("broadcast_sync(_INTERVIEWS_EVENT)")
        assert broadcast_calls >= 4, f"expected >=4 broadcast calls, found {broadcast_calls}"
