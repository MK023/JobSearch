"""Promotion pipeline: pre-AI gate + (in PR #2 step 4+) Anthropic analyzer.

This step (PR #2 step 3) implements only the gate. The actual analyzer call
+ cross-DB JobAnalysis insert lands in subsequent commits. Keeping the gate
isolated lets the rule-based filter ship and be observed in production
before any AI cost is incurred.

Flow:

    JobOffer (passed pre_filter, decision=promote)
        │
        ▼
    extract_stack(offer)        ← regex + canonical vocabulary
        │
        ▼
    score_match(stack)          ← against MARCO_CV_SKILLS
        │
        ├─ score < threshold ──► promotion_state = skipped_low_match
        │                        promotion_score = score
        │                        no AI call, no Neon write
        │
        └─ score >= threshold ─► promotion_state = pending
                                 promotion_score = score
                                 → continues into the analyzer (step 4)

The threshold is configurable via ``settings.promote_score_threshold``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import NamedTuple
from uuid import UUID

from sqlalchemy.orm import Session

from ...config import settings
from ..models import (
    PROMOTION_STATE_IDLE,
    PROMOTION_STATE_PENDING,
    PROMOTION_STATE_SKIPPED_LOW_MATCH,
    Decision,
    JobOffer,
)
from ..stack_extract import extract_stack
from ..stack_match import score_match


class PromotionGateResult(NamedTuple):
    """Outcome of the pre-AI gate for a single offer."""

    passed: bool  # True → continue to AI analyzer; False → skipped
    score: int  # stack-match score 0-100
    promotion_state: str  # value written to Decision.promotion_state
    matched: frozenset[str]
    missing: frozenset[str]


class PromotionGateError(Exception):
    """Raised when the offer or its decision row can't be loaded."""


def evaluate_for_promotion(
    db: Session,
    *,
    offer_id: UUID,
    threshold: int | None = None,
) -> PromotionGateResult:
    """Run the pre-AI gate on a single offer and persist the gate outcome.

    Loads the offer + its sibling decision, computes the stack-match score,
    and updates ``decision.promotion_state`` + ``decision.promotion_score``
    inline. Caller owns the commit.

    The actual AI analyzer call (PR #2 step 4) reads these fields and
    proceeds only when ``promotion_state == 'pending'``.
    """
    if threshold is None:
        threshold = settings.promote_score_threshold

    offer = db.get(JobOffer, offer_id)
    if offer is None:
        raise PromotionGateError(f"JobOffer {offer_id} not found")

    decision = db.query(Decision).filter(Decision.job_offer_id == offer_id).one_or_none()
    if decision is None:
        raise PromotionGateError(
            f"Decision row for offer {offer_id} not found — expected one to be created at ingest time"
        )

    # Build the dict shape that extract_stack expects (mirrors the Adzuna
    # adapter's normalized output, so the function works on either ingestion
    # path or replay).
    offer_dict = {
        "title": offer.title,
        "description": offer.description or "",
        "category": offer.category or "",
    }
    extracted = extract_stack(offer_dict)
    match = score_match(extracted)

    decision.promotion_score = match.score  # type: ignore[assignment]
    if match.score < threshold:
        decision.promotion_state = PROMOTION_STATE_SKIPPED_LOW_MATCH  # type: ignore[assignment]
        decision.promotion_started_at = None  # type: ignore[assignment]
        passed = False
        new_state = PROMOTION_STATE_SKIPPED_LOW_MATCH
    else:
        decision.promotion_state = PROMOTION_STATE_PENDING  # type: ignore[assignment]
        decision.promotion_started_at = datetime.now(UTC)  # type: ignore[assignment]
        passed = True
        new_state = PROMOTION_STATE_PENDING
    decision.promotion_error = ""  # type: ignore[assignment]
    db.flush()

    return PromotionGateResult(
        passed=passed,
        score=match.score,
        promotion_state=new_state,
        matched=match.matched,
        missing=match.missing,
    )


def reset_promotion_state(db: Session, *, offer_id: UUID) -> None:
    """Reset a decision's promotion fields back to idle.

    Useful when Marco changes his mind and re-clicks Promote: we want a
    clean slate (no stale ``skipped_low_match`` blocking the retry).
    """
    decision = db.query(Decision).filter(Decision.job_offer_id == offer_id).one_or_none()
    if decision is None:
        raise PromotionGateError(f"Decision row for offer {offer_id} not found")
    decision.promotion_state = PROMOTION_STATE_IDLE  # type: ignore[assignment]
    decision.promotion_score = None  # type: ignore[assignment]
    decision.promotion_started_at = None  # type: ignore[assignment]
    decision.promotion_error = ""  # type: ignore[assignment]
    db.flush()
