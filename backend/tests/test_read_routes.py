"""Tests for read-only API routes — real SQLite DB, no service mocks."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analysis.models import AnalysisStatus, JobAnalysis
from src.auth.models import User
from src.contacts.models import Contact
from src.cv.models import CVProfile
from src.database import get_db
from src.database.base import Base
from src.dependencies import get_current_user
from src.interview.models import Interview

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
def _user(_real_db):
    """Create a test user."""
    user = User(id=uuid.uuid4(), email="test@example.com", password_hash="$2b$12$fake")
    _real_db.add(user)
    _real_db.commit()
    return user


@pytest.fixture
def _cv(_real_db, _user):
    """Create a test CV."""
    cv = CVProfile(id=uuid.uuid4(), user_id=_user.id, raw_text="Test CV text " * 20, name="Tester")
    _real_db.add(cv)
    _real_db.commit()
    return cv


@pytest.fixture
def _analysis(_real_db, _cv):
    """Create a test analysis."""
    a = JobAnalysis(
        id=uuid.uuid4(),
        cv_id=_cv.id,
        job_description="Software Engineer position",
        company="TestCorp",
        role="Software Engineer",
        score=80,
        recommendation="APPLY",
        status=AnalysisStatus.APPLIED,
        strengths=["Python"],
        gaps=[],
        advice="Good match.",
        model_used="claude-haiku-4-5-20251001",
        tokens_input=100,
        tokens_output=50,
        cost_usd=0.001,
        content_hash="abc",
    )
    _real_db.add(a)
    _real_db.commit()
    return a


@pytest.fixture
def auth_client(_real_db, _user):
    """TestClient with real SQLite DB and authenticated user."""
    from contextlib import asynccontextmanager

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


class TestCandidatureEndpoints:
    def test_list_candidature_empty(self, auth_client):
        resp = auth_client.get("/api/v1/candidature")
        assert resp.status_code == 200
        assert resp.json()["candidature"] == []

    def test_list_candidature_with_data(self, auth_client, _analysis):
        resp = auth_client.get("/api/v1/candidature")
        assert resp.status_code == 200
        assert len(resp.json()["candidature"]) == 1

    def test_list_candidature_with_status_filter(self, auth_client, _analysis):
        resp = auth_client.get("/api/v1/candidature?status=candidato")
        assert resp.status_code == 200
        assert len(resp.json()["candidature"]) == 1

    def test_list_candidature_filter_no_match(self, auth_client, _analysis):
        resp = auth_client.get("/api/v1/candidature?status=scartato")
        assert resp.status_code == 200
        assert resp.json()["candidature"] == []

    def test_search_candidature(self, auth_client, _analysis):
        resp = auth_client.get("/api/v1/candidature/search?q=TestCorp")
        assert resp.status_code == 200
        assert len(resp.json()["candidature"]) == 1

    def test_search_candidature_no_results(self, auth_client, _analysis):
        resp = auth_client.get("/api/v1/candidature/search?q=nonexistent")
        assert resp.status_code == 200
        assert resp.json()["candidature"] == []

    def test_search_candidature_requires_query(self, auth_client):
        resp = auth_client.get("/api/v1/candidature/search")
        assert resp.status_code == 422

    def test_top_candidature(self, auth_client, _analysis):
        resp = auth_client.get("/api/v1/candidature/top")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["candidature"]) == 1
        assert data["candidature"][0]["score"] == 80

    def test_date_range(self, auth_client, _analysis):
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        resp = auth_client.get(f"/api/v1/candidature/date-range?date_from={today}&date_to={today}")
        assert resp.status_code == 200

    def test_date_range_invalid_format(self, auth_client):
        resp = auth_client.get("/api/v1/candidature/date-range?date_from=bad&date_to=bad")
        assert resp.status_code == 400

    def test_stale_candidature(self, auth_client):
        resp = auth_client.get("/api/v1/candidature/stale")
        assert resp.status_code == 200

    def test_stale_with_days_param(self, auth_client):
        resp = auth_client.get("/api/v1/candidature/stale?days=14")
        assert resp.status_code == 200


class TestCandidatureDetail:
    def test_found(self, auth_client, _analysis):
        resp = auth_client.get(f"/api/v1/candidature/{_analysis.id}")
        assert resp.status_code == 200
        assert resp.json()["company"] == "TestCorp"

    def test_not_found(self, auth_client):
        fake_id = str(uuid.uuid4())
        resp = auth_client.get(f"/api/v1/candidature/{fake_id}")
        assert resp.status_code == 404


class TestInterviewPrep:
    def test_not_found(self, auth_client):
        fake_id = str(uuid.uuid4())
        resp = auth_client.get(f"/api/v1/interview-prep/{fake_id}")
        assert resp.status_code == 404


class TestCoverLetters:
    def test_not_found(self, auth_client):
        fake_id = str(uuid.uuid4())
        resp = auth_client.get(f"/api/v1/cover-letters/{fake_id}")
        assert resp.status_code == 404


class TestContactsSearch:
    def test_search_contacts_empty(self, auth_client):
        resp = auth_client.get("/api/v1/contacts/search?q=marco")
        assert resp.status_code == 200
        assert resp.json()["contacts"] == []

    def test_search_contacts_with_data(self, auth_client, _real_db, _analysis):
        c = Contact(
            id=uuid.uuid4(),
            analysis_id=_analysis.id,
            name="Marco Rossi",
            company="TestCorp",
        )
        _real_db.add(c)
        _real_db.commit()
        resp = auth_client.get("/api/v1/contacts/search?q=Marco")
        assert resp.status_code == 200
        assert len(resp.json()["contacts"]) == 1

    def test_search_requires_query(self, auth_client):
        resp = auth_client.get("/api/v1/contacts/search")
        assert resp.status_code == 422


class TestFollowups:
    def test_pending_followups_empty(self, auth_client):
        resp = auth_client.get("/api/v1/followups/pending")
        assert resp.status_code == 200
        assert resp.json()["pending_followups"] == []


class TestActivitySummary:
    def test_activity_summary(self, auth_client):
        resp = auth_client.get("/api/v1/activity-summary?days=7")
        assert resp.status_code == 200
        data = resp.json()
        assert "period_days" in data
        assert data["avg_score"] == 0


class TestInterviewsUpcoming:
    def test_with_days_param(self, auth_client):
        resp = auth_client.get("/api/v1/interviews-upcoming?days=7")
        assert resp.status_code == 200

    def test_without_days_param(self, auth_client):
        resp = auth_client.get("/api/v1/interviews-upcoming")
        assert resp.status_code == 200

    def test_returns_upcoming_interviews(self, auth_client, _real_db, _analysis):
        future = datetime.now(UTC) + timedelta(days=3)
        interview = Interview(
            id=uuid.uuid4(),
            analysis_id=_analysis.id,
            scheduled_at=future,
            interview_type="technical",
            round_number=1,
        )
        _real_db.add(interview)
        _real_db.commit()
        resp = auth_client.get("/api/v1/interviews-upcoming?days=7")
        assert resp.status_code == 200
