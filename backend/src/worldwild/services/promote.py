"""Promotion pipeline: pre-AI gate + Anthropic analyzer + cross-DB JobAnalysis insert.

End-to-end flow:

    JobOffer (passed pre_filter, decision=promote)
        │
        ▼
    extract_stack(offer)            ← regex + canonical vocabulary
        │
        ▼
    score_match(stack)              ← against MARCO_CV_SKILLS
        │
        ├─ score < threshold ──────► state = skipped_low_match  (terminal)
        │                            no AI call, no Neon write
        │
        ├─ budget exhausted ───────► state = failed  (retryable)
        │                            no AI call, no Neon write
        │
        ├─ CV missing ─────────────► state = failed  (retryable after CV upload)
        │                            no AI call, no Neon write
        │
        └─ score ≥ threshold ──────► state = pending → run_analysis on Neon ──► state = done
                                     (uses analyze_job + add_spending pattern)

DRY: this service is **glue**, not new logic. All heavy lifting reuses
existing JobSearch primitives:

- ``cv.service.get_latest_cv``        — fetch the active CV
- ``analysis.service.run_analysis``   — calls analyze_job + persists JobAnalysis
- ``dashboard.service.check_budget_available`` / ``add_spending`` — budget ledger
- ``analysis.models.AnalysisSource.WORLDWILD`` — origin tag

Cross-DB: the JobAnalysis row lives on Neon (primary), the Decision row on
Supabase (secondary). The pointer ``Decision.promoted_to_neon_id`` is a bare
UUID with no FK constraint — Postgres can't enforce FKs across databases.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, NamedTuple
from uuid import UUID

from sqlalchemy.orm import Session

from ...analysis.models import AnalysisSource
from ...analysis.service import run_analysis
from ...config import settings
from ...cv.service import get_latest_cv
from ...dashboard.service import add_spending, check_budget_available
from ...notification_center.sse import broadcast_sync
from ..models import (
    PROMOTION_STATE_DONE,
    PROMOTION_STATE_FAILED,
    PROMOTION_STATE_IDLE,
    PROMOTION_STATE_PENDING,
    PROMOTION_STATE_SKIPPED_LOW_MATCH,
    Decision,
    JobOffer,
)
from ..stack_extract import extract_stack
from ..stack_match import score_match

if TYPE_CHECKING:
    from ...integrations.cache import CacheService

_logger = logging.getLogger(__name__)


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


# ── End-to-end promotion (gate + AI analyzer + cross-DB write) ─────────────


class PromotionResult(NamedTuple):
    """Outcome of the full promotion pipeline. Caller renders to UI / API."""

    state: str  # one of PROMOTION_STATE_*
    score: int  # stack-match score 0-100 (gate output)
    analysis_id: UUID | None  # JobAnalysis.id on Neon, when state == done
    cost_usd: float  # AI cost incurred (0 when skipped/failed)
    error: str  # short reason when state == failed
    # Motivo no-op quando saltiamo l'analisi senza errori (es. "already_done"
    # per idempotenza). Vuoto in tutti gli altri casi. Default per
    # backward-compat con i test esistenti che costruiscono PromotionResult
    # senza questo campo.
    skipped_reason: str = ""


def run_promotion_analysis(
    primary_db: Session,
    secondary_db: Session,
    *,
    offer_id: UUID,
    user_id: UUID,
    cache: CacheService | None = None,
    model: str = "haiku",
) -> PromotionResult:
    """Promote a WorldWild offer into a full JobAnalysis on the primary DB.

    Idempotent on the gate (re-running on a row already in
    ``skipped_low_match`` re-evaluates from scratch). Not idempotent on the
    AI call once it succeeds — a successful run flips the state to ``done``
    and a re-run will issue a NEW Claude call. Caller (UI / cron) is
    responsible for calling :func:`reset_promotion_state` first if a retry
    from scratch is desired.

    Caller owns the commits on both sessions: this function only flushes,
    so partial failures roll back cleanly when the caller's transaction
    rolls back. The two sessions commit independently (Neon + Supabase).
    """
    # 0. Idempotenza: se la decision è già in stato terminal "done",
    # short-circuit per evitare un nuovo Claude call (double-charge).
    # Per forzare un retry, il caller deve invocare reset_promotion_state()
    # che riporta a "idle".
    existing = secondary_db.query(Decision).filter(Decision.job_offer_id == offer_id).one_or_none()
    if existing is not None and existing.promotion_state == PROMOTION_STATE_DONE:
        return PromotionResult(
            state=PROMOTION_STATE_DONE,
            score=int(existing.promotion_score or 0),
            analysis_id=existing.promoted_to_neon_id,  # type: ignore[arg-type]
            cost_usd=0.0,
            error="",
            skipped_reason="already_done",
        )

    # 1. Gate (deterministic, no AI cost, persists promotion_state on secondary)
    gate = evaluate_for_promotion(secondary_db, offer_id=offer_id)
    # Notifica clienti SSE: lo state machine ha appena fatto una transizione
    # (idle → pending oppure idle → skipped_low_match). Il client ricarica
    # lo state via fetch su ricezione dell'evento.
    broadcast_sync("worldwild:promotion_state")
    if not gate.passed:
        return PromotionResult(
            state=PROMOTION_STATE_SKIPPED_LOW_MATCH,
            score=gate.score,
            analysis_id=None,
            cost_usd=0.0,
            error="",
        )

    decision = secondary_db.query(Decision).filter(Decision.job_offer_id == offer_id).one()
    offer = secondary_db.get(JobOffer, offer_id)
    if offer is None:  # pragma: no cover — gate would have raised first
        raise PromotionGateError(f"JobOffer {offer_id} disappeared mid-promotion")

    # 2. Budget gate (REUSE existing AppSettings ledger)
    budget_ok, budget_msg = check_budget_available(primary_db)
    if not budget_ok:
        return _mark_failed(decision, reason=budget_msg or "budget_exhausted", score=gate.score)

    # 3. Active CV (REUSE existing user CV pipeline)
    cv = get_latest_cv(primary_db, user_id)
    if cv is None:
        return _mark_failed(decision, reason="no_active_cv", score=gate.score)

    # 4. Run AI + persist JobAnalysis on Neon (REUSE run_analysis)
    try:
        analysis, result_dict = run_analysis(
            primary_db,
            cv_text=cv.raw_text,  # type: ignore[arg-type]
            cv_id=cv.id,  # type: ignore[arg-type]
            job_description=offer.description or "",  # type: ignore[arg-type]
            job_url=offer.url or "",  # type: ignore[arg-type]
            model=model,
            cache=cache,
            user_id=user_id,
            source=AnalysisSource.WORLDWILD.value,
        )
    except Exception as exc:  # noqa: BLE001 — surface analyzer failures to caller
        _logger.exception("worldwild promotion analyze failed (type=%s)", type(exc).__name__)
        return _mark_failed(decision, reason=f"analyzer:{type(exc).__name__}", score=gate.score)

    # 5. Spending tracking (REUSE existing AppSettings counters)
    add_spending(
        primary_db,
        cost=float(result_dict.get("cost_usd", 0.0)),
        tokens_in=int(result_dict.get("tokens", {}).get("input", 0)),
        tokens_out=int(result_dict.get("tokens", {}).get("output", 0)),
    )

    # 6. Cross-DB pointer + state transition
    decision.promoted_to_neon_id = analysis.id  # type: ignore[assignment]
    decision.promotion_state = PROMOTION_STATE_DONE  # type: ignore[assignment]
    decision.promotion_error = ""  # type: ignore[assignment]
    secondary_db.flush()

    # Notifica SSE: pending → done (Claude call completato, JobAnalysis su Neon)
    broadcast_sync("worldwild:promotion_state")

    return PromotionResult(
        state=PROMOTION_STATE_DONE,
        score=gate.score,
        analysis_id=analysis.id,  # type: ignore[arg-type]
        cost_usd=float(result_dict.get("cost_usd", 0.0)),
        error="",
    )


def _mark_failed(decision: Decision, *, reason: str, score: int) -> PromotionResult:
    """Set the decision to ``failed`` with a short reason; flush handled by caller."""
    decision.promotion_state = PROMOTION_STATE_FAILED  # type: ignore[assignment]
    decision.promotion_error = reason[:500]  # type: ignore[assignment]
    # Notifica SSE: transizione → failed (budget/CV/analyzer error)
    broadcast_sync("worldwild:promotion_state")
    return PromotionResult(
        state=PROMOTION_STATE_FAILED,
        score=score,
        analysis_id=None,
        cost_usd=0.0,
        error=reason,
    )
