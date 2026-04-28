"""Service helpers for the ``decide`` (skip / promote) action on a JobOffer.

Promotion to ``job_analyses`` on the primary DB is deferred to PR #2 — for now
``promote`` just marks the Decision row, so Marco can shortlist visually.
The cross-DB write happens in the AI-analyzer step.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    DECISION_PROMOTE,
    DECISION_SKIP,
    Decision,
    JobOffer,
)


class DecideError(Exception):
    """Raised on invalid decide input (unknown offer / decision)."""


def apply_decision(
    db: Session,
    *,
    offer_id: UUID,
    decision: str,
    reason: str = "",
) -> Decision:
    """Mark a JobOffer as skip or promote.

    Idempotent: re-deciding overwrites the existing row's decision + timestamp +
    reason. We don't keep a history of decisions in PR #1; if Marco changes his
    mind, the latest call wins. History goes in PR #5 if/when we wire up the
    auto-filter feedback loop.
    """
    if decision not in (DECISION_SKIP, DECISION_PROMOTE):
        raise DecideError(f"unknown decision: {decision!r}")

    offer = db.execute(select(JobOffer).where(JobOffer.id == offer_id)).scalar_one_or_none()
    if offer is None:
        raise DecideError(f"JobOffer {offer_id} not found")

    decision_row = db.execute(select(Decision).where(Decision.job_offer_id == offer_id)).scalar_one_or_none()
    if decision_row is None:
        decision_row = Decision(job_offer_id=offer_id)
        db.add(decision_row)

    # SQLAlchemy mypy plugin reports Column[X] descriptors as the assignment
    # target type, even though runtime resolves to bare values on instances.
    # Same pattern as elsewhere in the codebase (see inbox/service.py).
    decision_row.decision = decision  # type: ignore[assignment]
    decision_row.reason = (reason or "")[:500]  # type: ignore[assignment]
    decision_row.decided_at = datetime.now(UTC)  # type: ignore[assignment]
    db.flush()
    return decision_row
