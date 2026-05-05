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
from typing import Any, cast
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
    PROMOTION_STATE_DONE,
    PROMOTION_STATE_FAILED,
    Decision,
    JobOffer,
)
from src.worldwild.routes import _query_offers, _quick_counts

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
    """Insert a JobOffer + sibling pending Decision; return offer_id.

    ``cv_match_score`` impostato sopra la default threshold (50) così l'offer
    è visibile nei nuovi count by-source di ``_quick_counts``.
    """
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
        cv_match_score=80,
    )
    _secondary_db.add(offer)
    _secondary_db.flush()
    _secondary_db.add(Decision(job_offer_id=offer.id, decision=DECISION_PENDING))
    _secondary_db.commit()
    # cast: SQLAlchemy mypy plugin tipizza l'attributo come Column[UUID],
    # ma a runtime è un UUID Python (instance attribute post-flush).
    return cast(uuid.UUID, offer.id)


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


class TestWorldwildPage:
    """GET /worldwild — Jinja2 SSR page render.

    Closes the gap that let the ``strftime`` filter bug ship to prod (28/4):
    we had route-level tests for /decide and /promote but no test that
    actually rendered the template, so a Jinja exception only surfaced in
    Render logs after deploy.
    """

    def test_page_renders_200_with_no_offers(self, auth_client: Any) -> None:
        r = auth_client.get("/worldwild")
        assert r.status_code == 200
        assert "WorldWild" in r.text or "worldwild" in r.text.lower()

    def test_page_renders_200_with_offer_having_posted_at(self, auth_client: Any, _secondary_db: Any) -> None:
        # Exercise the strftime branch on posted_at — this is the exact
        # code path that crashed in prod before the |strftime → .strftime fix.
        from datetime import UTC
        from datetime import datetime as _dt

        offer = JobOffer(
            source="adzuna",
            external_id="ext-posted",
            content_hash="hash-posted",
            title="DevOps Engineer w/ timestamp",
            company="DateCorp",
            location="Roma",
            url="https://example.com/job-posted",
            description="Python, Kubernetes",
            pre_filter_passed=True,
            cv_match_score=75,
            posted_at=_dt(2026, 4, 28, 10, 0, tzinfo=UTC),
        )
        _secondary_db.add(offer)
        _secondary_db.flush()
        _secondary_db.add(Decision(job_offer_id=offer.id, decision=DECISION_PENDING))
        _secondary_db.commit()

        r = auth_client.get("/worldwild")
        assert r.status_code == 200
        # The offer card should render with the formatted date — Jinja's
        # `(o.posted_at|italytime).strftime('%d %b')` produces e.g. "28 Apr".
        assert "DevOps Engineer w/ timestamp" in r.text


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
    """POST /api/v1/worldwild/analizza/{offer_id} schedules a BackgroundTask."""

    def test_promote_returns_202_and_schedules_task(self, auth_client: Any, _seed_offer: uuid.UUID) -> None:
        # Patch the actual background body so we don't run the real
        # send-to-pulse cross-DB write.
        with patch("src.worldwild.routes._run_send_to_pulse_in_background") as mock_run:
            r = auth_client.post(f"/api/v1/worldwild/analizza/{_seed_offer}")
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
        with patch("src.worldwild.routes._run_send_to_pulse_in_background") as mock_run:
            r = auth_client.post(f"/api/v1/worldwild/analizza/{ghost}")
        assert r.status_code == 404
        mock_run.assert_not_called()

    def test_promote_invalid_offer_id_returns_400(self, auth_client: Any) -> None:
        r = auth_client.post("/api/v1/worldwild/analizza/not-a-uuid")
        assert r.status_code == 400


def _seed_offer_with_state(
    db: Any,
    *,
    source: str = "adzuna",
    cv_match_score: int | None = 80,
    promotion_state: str = "idle",
    decision: str = DECISION_PENDING,
) -> uuid.UUID:
    """Test helper: insert a JobOffer + matching Decision with explicit state.

    Centralizza la creazione di fixture per i test di filtering/counts: il
    seeding manuale ripetuto con kwargs dispersi rende i test illeggibili.
    """
    offer = JobOffer(
        source=source,
        external_id=f"ext-{uuid.uuid4().hex[:8]}",
        content_hash=f"hash-{uuid.uuid4().hex[:8]}",
        title="Test Offer",
        company="Co",
        location="Milano",
        url="https://example.com/job",
        description="Python",
        pre_filter_passed=True,
        cv_match_score=cv_match_score,
    )
    db.add(offer)
    db.flush()
    db.add(Decision(job_offer_id=offer.id, decision=decision, promotion_state=promotion_state))
    db.commit()
    return cast(uuid.UUID, offer.id)


class TestQueryOffersAutoHide:
    """``_query_offers`` esclude offers con ``promotion_state='done'`` (auto-hide)."""

    def test_done_offer_is_hidden(self, _secondary_db: Any) -> None:
        idle_id = _seed_offer_with_state(_secondary_db, promotion_state="idle")
        _seed_offer_with_state(_secondary_db, promotion_state=PROMOTION_STATE_DONE)
        offers = _query_offers(_secondary_db, only_pending=True, limit=50)
        ids = [cast(uuid.UUID, o.id) for o in offers]
        assert idle_id in ids
        assert len(offers) == 1

    def test_failed_offer_remains_visible_for_retry(self, _secondary_db: Any) -> None:
        # ``failed`` deve restare in lista — Marco vuole poterla ri-tentare.
        failed_id = _seed_offer_with_state(_secondary_db, promotion_state=PROMOTION_STATE_FAILED)
        offers = _query_offers(_secondary_db, only_pending=True, limit=50)
        assert failed_id in [cast(uuid.UUID, o.id) for o in offers]

    def test_idle_and_pending_states_visible(self, _secondary_db: Any) -> None:
        idle_id = _seed_offer_with_state(_secondary_db, promotion_state="idle")
        pending_id = _seed_offer_with_state(_secondary_db, promotion_state="pending")
        offers = _query_offers(_secondary_db, only_pending=True, limit=50)
        ids = [cast(uuid.UUID, o.id) for o in offers]
        assert idle_id in ids
        assert pending_id in ids


class TestQuickCountsKPIs:
    """``_quick_counts`` ritorna le 4 KPI dell'hero coerenti con la lista."""

    def test_returns_all_four_keys(self, _secondary_db: Any) -> None:
        counts = _quick_counts(_secondary_db)
        for key in ("pending", "score_ok", "score_na", "analyzed_total", "per_source"):
            assert key in counts

    def test_pending_excludes_done(self, _secondary_db: Any) -> None:
        _seed_offer_with_state(_secondary_db, cv_match_score=80, promotion_state="idle")
        _seed_offer_with_state(_secondary_db, cv_match_score=80, promotion_state=PROMOTION_STATE_DONE)
        counts = _quick_counts(_secondary_db)
        assert counts["pending"] == 1
        assert counts["analyzed_total"] == 1

    def test_score_ok_and_na_partition_pending(self, _secondary_db: Any) -> None:
        # 1 offer score>=threshold (ok), 1 offer score=None (n/d), 1 score sotto soglia
        _seed_offer_with_state(_secondary_db, cv_match_score=80)
        _seed_offer_with_state(_secondary_db, cv_match_score=None)
        _seed_offer_with_state(_secondary_db, cv_match_score=10)
        counts = _quick_counts(_secondary_db)
        assert counts["pending"] == 3
        assert counts["score_ok"] == 1
        assert counts["score_na"] == 1
        # Invariante: score_ok e score_na sono sotto-insiemi disgiunti di pending,
        # ma non lo coprono interamente (score basso-ma-non-null sta in pending senza
        # rientrare in nessuno dei due).
        assert counts["score_ok"] + counts["score_na"] <= counts["pending"]

    def test_analyzed_total_counts_done_decisions_unfiltered(self, _secondary_db: Any) -> None:
        # `analyzed_total` è cumulativo: deve contare anche done offer non più
        # in lista pending (è il funnel storico /worldwild → Pulse).
        _seed_offer_with_state(_secondary_db, promotion_state=PROMOTION_STATE_DONE, decision="promote")
        _seed_offer_with_state(_secondary_db, promotion_state=PROMOTION_STATE_DONE, decision="promote")
        _seed_offer_with_state(_secondary_db, promotion_state="idle")
        counts = _quick_counts(_secondary_db)
        assert counts["analyzed_total"] == 2
        assert counts["pending"] == 1
