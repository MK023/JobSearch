"""Tests for the pre-AI gate (PR #2 step 3): no AI call, no Neon write.

The gate runs against an in-memory SQLite worldwild DB so we can verify
both the score path and the persistence path (Decision row updated)
without touching Supabase or Anthropic.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.worldwild_db import WorldwildBase
from src.worldwild import audit_models, models  # noqa: F401  -- register tables
from src.worldwild.models import (
    DECISION_PENDING,
    PROMOTION_STATE_IDLE,
    PROMOTION_STATE_PENDING,
    PROMOTION_STATE_SKIPPED_LOW_MATCH,
    Decision,
    JobOffer,
)
from src.worldwild.services.promote import (
    PromotionGateError,
    evaluate_for_promotion,
    reset_promotion_state,
)


@pytest.fixture
def db_session() -> Any:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    WorldwildBase.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


def _seed_offer_with_decision(
    db: Any,
    *,
    title: str = "Senior DevOps Engineer",
    description: str = "Python, Kubernetes, AWS, Terraform",
) -> UUID:
    """Insert one JobOffer + sibling Decision (pending), return offer_id."""
    offer = JobOffer(
        source="adzuna",
        external_id=f"ext-{uuid4().hex[:8]}",
        content_hash=f"hash-{uuid4().hex[:16]}",
        title=title,
        company="TestCorp",
        location="Milano",
        url="https://example.com/job",
        description=description,
        pre_filter_passed=True,
        pre_filter_reason="",
    )
    db.add(offer)
    db.flush()
    db.add(Decision(job_offer_id=offer.id, decision=DECISION_PENDING))
    db.flush()
    return offer.id  # type: ignore[no-any-return]


class TestEvaluateForPromotion:
    def test_high_match_marks_pending(self, db_session: Any) -> None:
        # All four tokens are in MARCO_CV_SKILLS → score 100 → passes the
        # default threshold (50) → promotion_state = pending.
        offer_id = _seed_offer_with_decision(
            db_session,
            description="Python, Kubernetes, AWS, Terraform — full stack remote.",
        )
        result = evaluate_for_promotion(db_session, offer_id=offer_id)
        db_session.commit()

        assert result.passed is True
        assert result.score == 100
        assert result.promotion_state == PROMOTION_STATE_PENDING

        decision = db_session.query(Decision).filter(Decision.job_offer_id == offer_id).one()
        assert decision.promotion_state == PROMOTION_STATE_PENDING
        assert decision.promotion_score == 100
        assert decision.promotion_started_at is not None
        assert decision.promotion_error == ""

    def test_low_match_marks_skipped(self, db_session: Any) -> None:
        # Tokens not in Marco's CV (synthetic) → score 0 → below threshold.
        # We use a known-extractable but CV-absent token: "cobol" alone
        # isn't even in stack_extract vocabulary, so use real tokens that
        # aren't in MARCO_CV_SKILLS: openshift, vault, oauth.
        offer_id = _seed_offer_with_decision(
            db_session,
            title="Mainframe Specialist",
            description="OpenShift, Vault, OAuth integration on legacy stack.",
        )
        result = evaluate_for_promotion(db_session, offer_id=offer_id)
        db_session.commit()

        assert result.passed is False
        assert result.promotion_state == PROMOTION_STATE_SKIPPED_LOW_MATCH

        decision = db_session.query(Decision).filter(Decision.job_offer_id == offer_id).one()
        assert decision.promotion_state == PROMOTION_STATE_SKIPPED_LOW_MATCH
        assert decision.promotion_started_at is None  # not started — gate failed

    def test_threshold_is_configurable(self, db_session: Any) -> None:
        # Score 50 with threshold=80 → fails the gate.
        # Score 50 with threshold=30 → passes.
        # Use 2 tokens, only 1 in CV → score 50.
        offer_id = _seed_offer_with_decision(
            db_session,
            title="Engineer",
            description="Python developer with OpenShift experience.",
        )
        result_strict = evaluate_for_promotion(db_session, offer_id=offer_id, threshold=80)
        db_session.commit()
        assert result_strict.passed is False
        assert result_strict.score == 50

        # Reset & re-evaluate with looser threshold.
        reset_promotion_state(db_session, offer_id=offer_id)
        result_loose = evaluate_for_promotion(db_session, offer_id=offer_id, threshold=30)
        db_session.commit()
        assert result_loose.passed is True
        assert result_loose.score == 50

    def test_unknown_offer_raises(self, db_session: Any) -> None:
        ghost = uuid4()
        with pytest.raises(PromotionGateError, match="not found"):
            evaluate_for_promotion(db_session, offer_id=ghost)

    def test_offer_without_decision_raises(self, db_session: Any) -> None:
        # Insert an offer but no sibling Decision (shouldn't happen in the
        # real ingest flow, but the service must fail loudly if it does).
        offer = JobOffer(
            source="adzuna",
            external_id="ext-orphan",
            content_hash="hash-orphan",
            title="DevOps",
            company="X",
            pre_filter_passed=True,
        )
        db_session.add(offer)
        db_session.flush()
        with pytest.raises(PromotionGateError, match="Decision row .* not found"):
            evaluate_for_promotion(db_session, offer_id=offer.id)


class TestResetPromotionState:
    def test_clears_all_promotion_fields(self, db_session: Any) -> None:
        offer_id = _seed_offer_with_decision(
            db_session,
            description="Python, Kubernetes, AWS, Terraform.",
        )
        evaluate_for_promotion(db_session, offer_id=offer_id)
        db_session.commit()

        # Sanity: state is pending after evaluate.
        decision = db_session.query(Decision).filter(Decision.job_offer_id == offer_id).one()
        assert decision.promotion_state == PROMOTION_STATE_PENDING

        reset_promotion_state(db_session, offer_id=offer_id)
        db_session.commit()

        decision = db_session.query(Decision).filter(Decision.job_offer_id == offer_id).one()
        assert decision.promotion_state == PROMOTION_STATE_IDLE
        assert decision.promotion_score is None
        assert decision.promotion_started_at is None
        assert decision.promotion_error == ""

    def test_unknown_decision_raises(self, db_session: Any) -> None:
        with pytest.raises(PromotionGateError, match="not found"):
            reset_promotion_state(db_session, offer_id=uuid4())
