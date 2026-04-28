"""End-to-end tests for the full promotion pipeline (gate + AI + cross-DB write).

Mocks every external dependency (analyze_job, get_latest_cv, add_spending,
check_budget_available) so the test exercises promote.run_promotion_analysis
in isolation. The secondary DB is a real in-memory SQLite bound to
WorldwildBase; the "primary" DB is a mock object that records calls.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.worldwild_db import WorldwildBase
from src.worldwild import audit_models, models  # noqa: F401  -- register tables
from src.worldwild.models import (
    DECISION_PENDING,
    PROMOTION_STATE_DONE,
    PROMOTION_STATE_FAILED,
    PROMOTION_STATE_SKIPPED_LOW_MATCH,
    Decision,
    JobOffer,
)
from src.worldwild.services.promote import run_promotion_analysis


@pytest.fixture
def secondary_db() -> Any:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    WorldwildBase.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def primary_db_mock() -> MagicMock:
    """Stand-in for the primary (Neon) session."""
    return MagicMock(name="primary_db")


def _seed_high_match_offer(secondary_db: Any) -> UUID:
    """Insert a JobOffer + Decision pair with stack that fully matches CV."""
    offer = JobOffer(
        source="adzuna",
        external_id=f"ext-{uuid4().hex[:8]}",
        content_hash=f"hash-{uuid4().hex[:16]}",
        title="Senior DevOps Engineer",
        company="TestCorp",
        location="Milano",
        url="https://example.com/job/1",
        description="Python, Kubernetes, AWS, Terraform — full remote.",
        pre_filter_passed=True,
    )
    secondary_db.add(offer)
    secondary_db.flush()
    secondary_db.add(Decision(job_offer_id=offer.id, decision=DECISION_PENDING))
    secondary_db.flush()
    return offer.id  # type: ignore[no-any-return]


def _seed_low_match_offer(secondary_db: Any) -> UUID:
    offer = JobOffer(
        source="adzuna",
        external_id=f"ext-{uuid4().hex[:8]}",
        content_hash=f"hash-{uuid4().hex[:16]}",
        title="Mainframe Specialist",
        company="LegacyCo",
        location="Milano",
        url="https://example.com/job/2",
        description="OpenShift Vault OAuth — old stack.",
        pre_filter_passed=True,
    )
    secondary_db.add(offer)
    secondary_db.flush()
    secondary_db.add(Decision(job_offer_id=offer.id, decision=DECISION_PENDING))
    secondary_db.flush()
    return offer.id  # type: ignore[no-any-return]


def _fake_analysis_result() -> dict[str, Any]:
    return {
        "score": 82,
        "recommendation": "candidati",
        "company": "TestCorp",
        "role": "Senior DevOps Engineer",
        "tokens": {"input": 1234, "output": 567},
        "cost_usd": 0.0123,
        "model_used": "claude-haiku-4-5-20251001",
    }


class TestSkipPaths:
    def test_low_match_returns_skipped(self, secondary_db: Any, primary_db_mock: MagicMock) -> None:
        offer_id = _seed_low_match_offer(secondary_db)
        result = run_promotion_analysis(
            primary_db_mock,
            secondary_db,
            offer_id=offer_id,
            user_id=uuid4(),
        )
        assert result.state == PROMOTION_STATE_SKIPPED_LOW_MATCH
        assert result.analysis_id is None
        assert result.cost_usd == 0.0
        # Primary DB must not have been touched at all on the skip path.
        primary_db_mock.query.assert_not_called()
        primary_db_mock.add.assert_not_called()


class TestFailedPaths:
    def test_budget_exhausted_marks_failed(self, secondary_db: Any, primary_db_mock: MagicMock) -> None:
        offer_id = _seed_high_match_offer(secondary_db)
        with (
            patch(
                "src.worldwild.services.promote.check_budget_available",
                return_value=(False, "Budget esaurito! Speso $5.10 su $5.00"),
            ),
            patch("src.worldwild.services.promote.run_analysis") as mock_run,
        ):
            result = run_promotion_analysis(
                primary_db_mock,
                secondary_db,
                offer_id=offer_id,
                user_id=uuid4(),
            )
        assert result.state == PROMOTION_STATE_FAILED
        assert "Budget esaurito" in result.error
        mock_run.assert_not_called()

        decision = secondary_db.query(Decision).filter(Decision.job_offer_id == offer_id).one()
        assert decision.promotion_state == PROMOTION_STATE_FAILED
        assert "Budget" in decision.promotion_error

    def test_no_active_cv_marks_failed(self, secondary_db: Any, primary_db_mock: MagicMock) -> None:
        offer_id = _seed_high_match_offer(secondary_db)
        with (
            patch(
                "src.worldwild.services.promote.check_budget_available",
                return_value=(True, ""),
            ),
            patch("src.worldwild.services.promote.get_latest_cv", return_value=None),
            patch("src.worldwild.services.promote.run_analysis") as mock_run,
        ):
            result = run_promotion_analysis(
                primary_db_mock,
                secondary_db,
                offer_id=offer_id,
                user_id=uuid4(),
            )
        assert result.state == PROMOTION_STATE_FAILED
        assert result.error == "no_active_cv"
        mock_run.assert_not_called()

    def test_run_analysis_exception_marks_failed(self, secondary_db: Any, primary_db_mock: MagicMock) -> None:
        offer_id = _seed_high_match_offer(secondary_db)
        fake_cv = MagicMock(raw_text="Sono Marco. Stack: Python.", id=uuid4())
        with (
            patch(
                "src.worldwild.services.promote.check_budget_available",
                return_value=(True, ""),
            ),
            patch("src.worldwild.services.promote.get_latest_cv", return_value=fake_cv),
            patch(
                "src.worldwild.services.promote.run_analysis",
                side_effect=RuntimeError("anthropic 500"),
            ),
            patch("src.worldwild.services.promote.add_spending") as mock_spend,
        ):
            result = run_promotion_analysis(
                primary_db_mock,
                secondary_db,
                offer_id=offer_id,
                user_id=uuid4(),
            )
        assert result.state == PROMOTION_STATE_FAILED
        assert "RuntimeError" in result.error
        # No spending recorded on a failed call (analyze_job never completed).
        mock_spend.assert_not_called()


class TestHappyPath:
    def test_happy_path_done(self, secondary_db: Any, primary_db_mock: MagicMock) -> None:
        offer_id = _seed_high_match_offer(secondary_db)
        fake_cv = MagicMock(raw_text="Marco CV", id=uuid4())
        fake_analysis = MagicMock(id=uuid4())
        with (
            patch(
                "src.worldwild.services.promote.check_budget_available",
                return_value=(True, ""),
            ),
            patch("src.worldwild.services.promote.get_latest_cv", return_value=fake_cv),
            patch(
                "src.worldwild.services.promote.run_analysis",
                return_value=(fake_analysis, _fake_analysis_result()),
            ) as mock_run,
            patch("src.worldwild.services.promote.add_spending") as mock_spend,
        ):
            result = run_promotion_analysis(
                primary_db_mock,
                secondary_db,
                offer_id=offer_id,
                user_id=uuid4(),
                model="haiku",
            )

        assert result.state == PROMOTION_STATE_DONE
        assert result.analysis_id == fake_analysis.id
        assert result.cost_usd == 0.0123
        assert result.score == 100  # high-match offer → 100% (all 4 tokens in CV)

        # run_analysis was called with source=worldwild
        kwargs = mock_run.call_args.kwargs
        assert kwargs["source"] == "worldwild"
        assert kwargs["cv_text"] == "Marco CV"
        assert kwargs["job_url"] == "https://example.com/job/1"
        assert kwargs["model"] == "haiku"

        # add_spending was called with the result's cost + tokens
        mock_spend.assert_called_once()
        spending_kwargs = mock_spend.call_args.kwargs
        assert spending_kwargs["cost"] == 0.0123
        assert spending_kwargs["tokens_in"] == 1234
        assert spending_kwargs["tokens_out"] == 567

        # Decision row updated with cross-DB pointer + done state
        decision = secondary_db.query(Decision).filter(Decision.job_offer_id == offer_id).one()
        assert decision.promotion_state == PROMOTION_STATE_DONE
        assert decision.promoted_to_neon_id == fake_analysis.id
        assert decision.promotion_error == ""
