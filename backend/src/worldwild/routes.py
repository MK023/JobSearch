"""WorldWild HTTP routes — page (HTML) + API (JSON).

Two routers exported:

- ``page_router``: GET ``/worldwild`` — Jinja2-rendered offer list. Mounted at
  the application root in ``main.py``.
- ``api_router``:  POST ``/worldwild/decide/{offer_id}``,
                   POST ``/worldwild/promote/{offer_id}`` (background task),
                   POST ``/worldwild/ingest/adzuna``. Mounted under
                   ``/api/v1`` in ``api_v1.py``.

Both depend on the secondary DB being configured; ``WorldwildEnabledGuard``
returns 503 with a clear message when it isn't.
"""

from __future__ import annotations

import logging
from typing import cast
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..audit.service import dual_audit
from ..database import SessionLocal as PrimarySessionLocal
from ..database.worldwild_db import WorldwildSessionLocal
from ..dependencies import CurrentUser, DbSession
from ..pages import _base_ctx
from .dependencies import WorldwildDbSession, WorldwildEnabledGuard
from .filters import has_remote_hint
from .models import (
    DECISION_PENDING,
    Decision,
    JobOffer,
)
from .schemas import DecideResponse, DecisionLiteral, IngestResponse, PromoteResponse
from .service_decide import DecideError, apply_decision
from .services.ingest import run_adzuna_ingest
from .services.promote import run_promotion_analysis

_logger = logging.getLogger(__name__)

# -- Page (HTML) ---------------------------------------------------------------------
page_router = APIRouter(tags=["worldwild-page"])


@page_router.get("/worldwild", response_class=HTMLResponse)
def worldwild_page(
    request: Request,
    user: CurrentUser,
    db: WorldwildDbSession,
    primary_db: DbSession,
    _guard: WorldwildEnabledGuard,
    only_pending: bool = Query(default=True),
    limit: int = Query(default=50, ge=1, le=200),
) -> HTMLResponse:
    """Render the WorldWild discovery page.

    Default view: pre-filter-passed offers whose decision is still pending.
    Toggle ``only_pending=false`` to inspect rejected/promoted history too.

    Context includes the standard sidebar/header keys via ``_base_ctx`` so
    notification/interview/pending badges render consistently across pages.
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
                **_base_ctx(primary_db, user, "worldwild"),
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


@api_router.post("/decide/{offer_id}", response_model=DecideResponse)
def decide_offer(
    request: Request,
    offer_id: str,
    user: CurrentUser,
    db: WorldwildDbSession,
    primary_db: DbSession,
    _guard: WorldwildEnabledGuard,
    decision: DecisionLiteral = Query(..., description="One of: skip, promote"),
    reason: str = Query(default="", max_length=500),
) -> DecideResponse:
    """Mark a JobOffer as skip or promote. Idempotent.

    ``decision`` is type-narrowed to ``Literal["skip","promote"]`` at the
    boundary — Pydantic rejects anything else with a 422. This is the
    architectural fix for Sonar S5145 that replaces the
    ``_SAFE_DECISION_LABELS`` dict workaround used in PR #197.

    Audit writes to the AUDIT table on the PRIMARY DB (Neon), so we need
    both sessions injected — secondary for the decision, primary for the
    audit log. Two separate commits, each on its own session.
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
    # ``decision`` is now Literal-typed → Sonar S5145 is satisfied at the
    # source. No dict trick, no cast(), no NOSONAR shim.
    _logger.info("worldwild decide ok: decision=%s", decision)
    return DecideResponse(
        ok=True,
        offer_id=str(decision_row.job_offer_id),
        decision=decision,
    )


def _run_promotion_in_background(offer_id: UUID, user_id: UUID) -> None:
    """Background task body: opens fresh sessions on BOTH DBs and runs promotion.

    Mirrors the ``inbox/routes.py`` pattern (fresh ``SessionLocal()`` instead
    of reusing the request session) but with the cross-DB twist: the WorldWild
    ingest layer needs both the primary (Neon) session for CV / JobAnalysis /
    audit and the secondary (Supabase) session for the Decision update.

    Errors are logged and swallowed — the route already returned 202 to the
    client, so a re-raise here only pollutes the worker process logs without
    informing the user. Sentry breadcrumb captures the exception.
    """
    primary_db = PrimarySessionLocal()
    secondary_db = WorldwildSessionLocal() if WorldwildSessionLocal is not None else None
    if secondary_db is None:  # pragma: no cover — guarded earlier in route
        primary_db.close()
        return
    try:
        run_promotion_analysis(
            primary_db,
            secondary_db,
            offer_id=offer_id,
            user_id=user_id,
        )
        primary_db.commit()
        secondary_db.commit()
    except Exception:
        _logger.exception("worldwild promote background task failed (offer=%s)", offer_id)
        primary_db.rollback()
        secondary_db.rollback()
    finally:
        primary_db.close()
        secondary_db.close()


@api_router.post("/promote/{offer_id}", response_model=PromoteResponse, status_code=202)
def promote_offer(
    request: Request,
    offer_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    db: WorldwildDbSession,
    primary_db: DbSession,
    _guard: WorldwildEnabledGuard,
) -> PromoteResponse:
    """Schedule a full promotion pipeline run in the background.

    Returns 202 Accepted immediately so the UI doesn't block on a 5-15s
    Anthropic call. The actual gate + analyzer + cross-DB write runs in a
    BackgroundTask spawned with fresh DB sessions — see
    :func:`_run_promotion_in_background`. The UI polls or listens via SSE
    for the terminal state on ``Decision.promotion_state``.
    """
    try:
        offer_uuid = UUID(offer_id)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid offer_id") from exc

    if db.get(JobOffer, offer_uuid) is None:
        raise HTTPException(status_code=404, detail="JobOffer not found")

    # Detach the user_id before passing to the background task — the
    # task uses fresh sessions and shouldn't rely on the request user object.
    user_id: UUID = user.id  # type: ignore[assignment]
    background_tasks.add_task(_run_promotion_in_background, offer_uuid, user_id)

    dual_audit(
        primary_db,
        db,
        request,
        "worldwild_promote_scheduled",
        f"offer={offer_id}",
    )
    primary_db.commit()
    db.commit()
    _logger.info("worldwild promote scheduled (offer=%s)", offer_uuid)
    return PromoteResponse(
        accepted=True,
        offer_id=str(offer_uuid),
        state="pending",
        message="Promotion scheduled — poll Decision.promotion_state for terminal status.",
    )


@api_router.post("/ingest/adzuna", response_model=IngestResponse)
def trigger_adzuna_ingest(
    request: Request,
    user: CurrentUser,
    db: WorldwildDbSession,
    primary_db: DbSession,
    _guard: WorldwildEnabledGuard,
) -> IngestResponse:
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
    return IngestResponse(
        ok=True,
        run_id=result.run_id,
        fetched=result.fetched,
        new=result.new,
        filtered_out=result.filtered_out,
    )
