"""WorldWild HTTP routes — page (HTML) + API (JSON).

Two routers exported:

- ``page_router``: GET ``/worldwild`` — Jinja2-rendered offer list. Mounted at
  the application root in ``main.py``.
- ``api_router``:  POST ``/worldwild/decide/{offer_id}`` and
                   POST ``/worldwild/ingest/adzuna``. Mounted under
                   ``/api/v1`` in ``api_v1.py``.

Both depend on the secondary DB being configured; ``WorldwildEnabledGuard``
returns 503 with a clear message when it isn't.
"""

from __future__ import annotations

import logging
from typing import cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..audit.service import dual_audit
from ..dependencies import CurrentUser, DbSession
from .dependencies import WorldwildDbSession, WorldwildEnabledGuard
from .filters import has_remote_hint
from .models import (
    ALL_DECISIONS,
    DECISION_PENDING,
    DECISION_PROMOTE,
    DECISION_SKIP,
    Decision,
    JobOffer,
)
from .service_decide import DecideError, apply_decision
from .services.ingest import run_adzuna_ingest

_logger = logging.getLogger(__name__)

# Hardcoded label map for safe logging — Sonar S5145 won't taint-track values
# selected from a constant dict, even though the underlying field came from
# user input. The fallback "unknown" is unreachable in practice (apply_decision
# raises DecideError on invalid input) but keeps the lookup total.
_SAFE_DECISION_LABELS: dict[str, str] = {
    DECISION_SKIP: "skip",
    DECISION_PROMOTE: "promote",
}

# -- Page (HTML) ---------------------------------------------------------------------
page_router = APIRouter(tags=["worldwild-page"])


@page_router.get("/worldwild", response_class=HTMLResponse)
def worldwild_page(
    request: Request,
    user: CurrentUser,
    db: WorldwildDbSession,
    _guard: WorldwildEnabledGuard,
    only_pending: bool = Query(default=True),
    limit: int = Query(default=50, ge=1, le=200),
) -> HTMLResponse:
    """Render the WorldWild discovery page.

    Default view: pre-filter-passed offers whose decision is still pending.
    Toggle ``only_pending=false`` to inspect rejected/promoted history too.
    """
    offers = _query_offers(db, only_pending=only_pending, limit=limit)
    counts = _quick_counts(db)
    rows = [
        {
            "id": str(o.id),
            "title": o.title,
            "company": o.company,
            "location": o.location,
            "url": o.url,
            "salary_min": o.salary_min,
            "salary_max": o.salary_max,
            "salary_currency": o.salary_currency,
            "contract_type": o.contract_type,
            "contract_time": o.contract_time,
            "category": o.category,
            "posted_at": o.posted_at,
            "ingested_at": o.ingested_at,
            "remote_hint": has_remote_hint(
                {
                    "title": o.title,
                    "description": o.description or "",
                    "location": o.location or "",
                }
            ),
            "source": o.source,
        }
        for o in offers
    ]
    templates = request.app.state.templates
    return cast(
        HTMLResponse,
        templates.TemplateResponse(
            request,
            "worldwild.html",
            {
                "user": user,
                "offers": rows,
                "counts": counts,
                "only_pending": only_pending,
            },
        ),
    )


def _query_offers(db: Session, *, only_pending: bool, limit: int) -> list[JobOffer]:
    """Return offers passing pre-filter, ordered by ingest recency.

    Pending-only filter is implemented via a NOT EXISTS / left-outer-join on
    ``decisions``: an offer counts as pending when its sole decision row has
    ``decision='pending'``.
    """
    stmt = (
        select(JobOffer).where(JobOffer.pre_filter_passed.is_(True)).order_by(desc(JobOffer.ingested_at)).limit(limit)
    )
    if only_pending:
        pending_ids = select(Decision.job_offer_id).where(Decision.decision == DECISION_PENDING)
        stmt = stmt.where(JobOffer.id.in_(pending_ids))
    return list(db.execute(stmt).scalars())


def _quick_counts(db: Session) -> dict[str, int]:
    """Counts surfaced as small badges in the page header."""
    total_passed = db.execute(select(func.count(JobOffer.id)).where(JobOffer.pre_filter_passed.is_(True))).scalar_one()
    total_filtered_out = db.execute(
        select(func.count(JobOffer.id)).where(JobOffer.pre_filter_passed.is_(False))
    ).scalar_one()
    pending = db.execute(select(func.count(Decision.id)).where(Decision.decision == DECISION_PENDING)).scalar_one()
    return {
        "total_passed": int(total_passed),
        "total_filtered_out": int(total_filtered_out),
        "pending": int(pending),
    }


# -- API (JSON) ----------------------------------------------------------------------
api_router = APIRouter(prefix="/worldwild", tags=["worldwild-api"])


@api_router.post("/decide/{offer_id}")
def decide_offer(
    request: Request,
    offer_id: str,
    user: CurrentUser,
    db: WorldwildDbSession,
    primary_db: DbSession,
    _guard: WorldwildEnabledGuard,
    decision: str = Query(..., description=f"One of: {','.join(ALL_DECISIONS)}"),
    reason: str = Query(default=""),
) -> JSONResponse:
    """Mark a JobOffer as skip or promote. Idempotent.

    Note: ``audit()`` writes to the AUDIT table on the PRIMARY DB (Neon), so we
    need both sessions injected — secondary for the actual decision, primary
    for the audit log row. Two separate commits, each on its own session.
    """
    try:
        offer_uuid = UUID(offer_id)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid offer_id") from exc

    try:
        decision_row = apply_decision(db, offer_id=offer_uuid, decision=decision, reason=reason)
    except DecideError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    db.commit()
    dual_audit(
        primary_db,
        db,
        request,
        "worldwild_decide",
        f"offer={offer_id} decision={decision}",
    )
    primary_db.commit()
    db.commit()
    # Sonar S5145 (logging user-controlled data) — log the decision as a
    # hardcoded-dict-mapped label, not the raw field. Sonar correctly
    # untaints values that come from a constant lookup. The offer id is
    # dropped from the log line entirely; it lives in the audit row that
    # we just committed and is reachable from there for diagnostics.
    # cast() because SQLAlchemy mypy plugin reports decision_row.decision as
    # Column[str] for the dict lookup; at runtime it's the bare string.
    safe_label = _SAFE_DECISION_LABELS.get(cast(str, decision_row.decision), "unknown")
    _logger.info("worldwild decide ok: decision=%s", safe_label)
    return JSONResponse(
        {
            "ok": True,
            "offer_id": str(decision_row.job_offer_id),
            "decision": decision_row.decision,
        }
    )


@api_router.post("/ingest/adzuna")
def trigger_adzuna_ingest(
    request: Request,
    user: CurrentUser,
    db: WorldwildDbSession,
    primary_db: DbSession,
    _guard: WorldwildEnabledGuard,
) -> JSONResponse:
    """Manually trigger an Adzuna ingest run.

    Synchronous on purpose (PR #1): the run takes ~5–15 s for 4 queries × 50
    results × 4 pages and Marco wants to see numbers right away. Cron schedule
    is added in PR #4.
    """
    try:
        result = run_adzuna_ingest(db, run_type="manual")
        db.commit()
    except Exception as exc:  # noqa: BLE001 — surface adapter failure to caller
        # Sonar S5145: log only the exception type (a class name, never
        # user-controlled). The full traceback + message is captured by
        # _logger.exception() automatically in the structured exc_info,
        # which Sentry / log aggregators consume out-of-band — not via
        # the format string interpolation.
        _logger.exception("worldwild ingest failed (type=%s)", type(exc).__name__)
        db.rollback()
        raise HTTPException(status_code=502, detail="Adzuna ingest failed") from exc

    dual_audit(
        primary_db,
        db,
        request,
        "worldwild_ingest",
        f"source=adzuna run={result.run_id} new={result.new}",
    )
    primary_db.commit()
    db.commit()
    return JSONResponse(
        {
            "ok": True,
            "run_id": result.run_id,
            "fetched": result.fetched,
            "new": result.new,
            "filtered_out": result.filtered_out,
        }
    )
