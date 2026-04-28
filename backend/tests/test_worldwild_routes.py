"""Route-level tests for WorldWild endpoints — TestClient + dual SQLite DBs.

Mirrors the pattern from ``test_batch_routes.py`` but runs the request
through both:
- a primary in-memory SQLite for users/audit/JobAnalysis (Base.metadata)
- a secondary in-memory SQLite for WorldWild (WorldwildBase.metadata)

Both are wired into the FastAPI app via ``dependency_overrides``. The
WorldWild enabled-guard is also overridden so the route doesn't return 503
in tests.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.auth.models import User
from src.database import get_db
from src.database.base import Base
from src.database.worldwild_db import WorldwildBase, get_worldwild_db
from src.dependencies import get_current_user
from src.worldwild import audit_models, models  # noqa: F401  -- register tables
from src.worldwild.dependencies import ensure_worldwild_enabled
from src.worldwild.models import (
    DECISION_PENDING,
    DECISION_PROMOTE,
    DECISION_SKIP,
    Decision,
    JobOffer,
)

# Ensure all models are registered with Base.metadata.
from tests.conftest import _ALL_MODELS  # noqa: F401


@pytest.fixture
def _primary_db() -> Any:
    """In-memory SQLite for users/audit/JobAnalysis (primary, Neon-equivalent)."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def _secondary_db() -> Any:
    """In-memory SQLite for WorldWild (secondary, Supabase-equivalent)."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    WorldwildBase.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def _http_user(_primary_db: Any) -> User:
    user = User(id=uuid.uuid4(), email="ww@test.com", password_hash="$2b$12$fake")
    _primary_db.add(user)
    _primary_db.commit()
    return user


@pytest.fixture
def _seed_offer(_secondary_db: Any) -> uuid.UUID:
    """Insert a JobOffer + sibling pending Decision; return offer_id."""
    offer = JobOffer(
        source="adzuna",
        external_id="ext-test",
        content_hash="hash-test",
        title="Senior DevOps Engineer",
        company="TestCorp",
        location="Milano",
        url="https://example.com/job",
        description="Python, Kubernetes, AWS",
        pre_filter_passed=True,
    )
    _secondary_db.add(offer)
    _secondary_db.flush()
    _secondary_db.add(Decision(job_offer_id=offer.id, decision=DECISION_PENDING))
    _secondary_db.commit()
    return offer.id  # type: ignore[no-any-return]


@pytest.fixture
def auth_client(_primary_db: Any, _secondary_db: Any, _http_user: User) -> Any:
    """Authenticated TestClient with both primary and secondary DBs wired."""
    from src.main import create_app

    @asynccontextmanager
    async def _test_lifespan(app: Any) -> Any:
        from src.integrations.cache import NullCacheService

        app.state.cache = NullCacheService()
        yield

    def _primary() -> Any:
        yield _primary_db

    def _secondary() -> Any:
        yield _secondary_db

    with patch("src.main.lifespan", _test_lifespan), patch("src.main.settings") as s:
        s.trusted_hosts_list = ["*"]
        s.cors_origins_list = ["*"]
        s.cors_allow_credentials = True
        s.secret_key = "test-secret"
        s.max_job_desc_size = 10000
        s.max_batch_size = 10
        s.rate_limit_analyze = "100/minute"
        s.rate_limit_default = "100/minute"
        app = create_app()
        app.dependency_overrides[get_db] = _primary
        app.dependency_overrides[get_worldwild_db] = _secondary
        app.dependency_overrides[get_current_user] = lambda: _http_user
        app.dependency_overrides[ensure_worldwild_enabled] = lambda: None
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client


class TestDecideEndpoint:
    """POST /api/v1/worldwild/decide/{offer_id} with Literal-validated decision."""

    def test_decide_skip_returns_200(self, auth_client: Any, _seed_offer: uuid.UUID, _secondary_db: Any) -> None:
        r = auth_client.post(f"/api/v1/worldwild/decide/{_seed_offer}?decision=skip")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["decision"] == "skip"
        assert body["offer_id"] == str(_seed_offer)
        # DB row updated
        decision = _secondary_db.query(Decision).filter(Decision.job_offer_id == _seed_offer).one()
        assert decision.decision == DECISION_SKIP

    def test_decide_promote_returns_200(self, auth_client: Any, _seed_offer: uuid.UUID, _secondary_db: Any) -> None:
        r = auth_client.post(f"/api/v1/worldwild/decide/{_seed_offer}?decision=promote")
        assert r.status_code == 200
        assert r.json()["decision"] == "promote"
        decision = _secondary_db.query(Decision).filter(Decision.job_offer_id == _seed_offer).one()
        assert decision.decision == DECISION_PROMOTE

    def test_decide_invalid_decision_returns_422(self, auth_client: Any, _seed_offer: uuid.UUID) -> None:
        # Literal["skip","promote"] rejects everything else with Pydantic 422
        r = auth_client.post(f"/api/v1/worldwild/decide/{_seed_offer}?decision=garbage")
        assert r.status_code == 422

    def test_decide_invalid_offer_id_returns_400(self, auth_client: Any) -> None:
        r = auth_client.post("/api/v1/worldwild/decide/not-a-uuid?decision=skip")
        assert r.status_code == 400

    def test_decide_unknown_offer_returns_400(self, auth_client: Any) -> None:
        ghost = uuid.uuid4()
        r = auth_client.post(f"/api/v1/worldwild/decide/{ghost}?decision=skip")
        assert r.status_code == 400  # JobOffer not found → DecideError


class TestPromoteEndpoint:
    """POST /api/v1/worldwild/promote/{offer_id} schedules a BackgroundTask."""

    def test_promote_returns_202_and_schedules_task(self, auth_client: Any, _seed_offer: uuid.UUID) -> None:
        # Patch the actual background body so we don't run the real
        # promotion (which would try to talk to Anthropic).
        with patch("src.worldwild.routes._run_promotion_in_background") as mock_run:
            r = auth_client.post(f"/api/v1/worldwild/promote/{_seed_offer}")
        assert r.status_code == 202
        body = r.json()
        assert body["accepted"] is True
        assert body["offer_id"] == str(_seed_offer)
        assert body["state"] == "pending"
        # The task body was scheduled — TestClient runs background tasks
        # synchronously after the response, so the call has already
        # fired by the time we assert.
        mock_run.assert_called_once()
        call_args = mock_run.call_args.args
        assert call_args[0] == _seed_offer  # offer_uuid

    def test_promote_unknown_offer_returns_404(self, auth_client: Any) -> None:
        ghost = uuid.uuid4()
        with patch("src.worldwild.routes._run_promotion_in_background") as mock_run:
            r = auth_client.post(f"/api/v1/worldwild/promote/{ghost}")
        assert r.status_code == 404
        mock_run.assert_not_called()

    def test_promote_invalid_offer_id_returns_400(self, auth_client: Any) -> None:
        r = auth_client.post("/api/v1/worldwild/promote/not-a-uuid")
        assert r.status_code == 400
