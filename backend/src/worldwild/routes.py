"""WorldWild HTTP routes — page (HTML) + API (JSON).

Two routers exported:

- ``page_router``: GET ``/worldwild`` — Jinja2-rendered offer list. Mounted at
  the application root in ``main.py``.
- ``api_router``:  POST ``/worldwild/decide/{offer_id}``,
                   POST ``/worldwild/analizza/{offer_id}`` (background task),
                   POST ``/worldwild/ingest/adzuna``. Mounted under
                   ``/api/v1`` in ``api_v1.py``.

Both depend on the secondary DB being configured; ``WorldwildEnabledGuard``
returns 503 with a clear message when it isn't.
"""

from __future__ import annotations

import logging
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..audit.service import dual_audit
from ..config import settings
from ..database import SessionLocal as PrimarySessionLocal
from ..database.worldwild_db import WorldwildSessionLocal
from ..dependencies import CurrentUser, DbSession
from ..pages import _base_ctx
from .dependencies import WorldwildDbSession, WorldwildEnabledGuard
from .filters import has_remote_hint
from .models import (
    ALL_SOURCES,
    DECISION_PENDING,
    PROMOTION_STATE_DONE,
    Decision,
    JobOffer,
)
from .schemas import DecideResponse, DecisionLiteral, IngestResponse, PromoteResponse
from .service_decide import DecideError, apply_decision
from .services.ingest import (
    run_adzuna_ingest,
    run_arbeitnow_ingest,
    run_findwork_ingest,
    run_jobicy_ingest,
    run_remoteok_ingest,
    run_remotive_ingest,
    run_themuse_ingest,
    run_weworkremotely_ingest,
    run_workingnomads_ingest,
)
from .services.promote import send_to_pulse

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
            "cv_match_score": o.cv_match_score,
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

    Auto-hide post-Analizza: offers la cui ``Decision.promotion_state`` è
    ``done`` vengono escluse — sono già state spedite a Pulse e non
    appartengono più alla vista "lista da decidere". Le altre (idle/pending/
    failed) restano visibili così che ``failed`` possa essere ri-tentato.
    """
    stmt = (
        select(JobOffer).where(JobOffer.pre_filter_passed.is_(True)).order_by(desc(JobOffer.ingested_at)).limit(limit)
    )
    not_done_ids = select(Decision.job_offer_id).where(Decision.promotion_state != PROMOTION_STATE_DONE)
    stmt = stmt.where(JobOffer.id.in_(not_done_ids))
    if only_pending:
        pending_ids = select(Decision.job_offer_id).where(Decision.decision == DECISION_PENDING)
        stmt = stmt.where(JobOffer.id.in_(pending_ids))
    return list(db.execute(stmt).scalars())


def _quick_counts(db: Session) -> dict[str, Any]:
    """KPI hero + breakdown per source, coerenti con la lista visibile a Marco.

    Pattern allineato a /agenda (``feedback_pattern_consistency_default``): le
    badge dell'header contano righe a schermo, non totali raw del DB. La lista
    visibile è definita da:

    - ``pre_filter_passed = TRUE`` (regole rule-based pre-AI)
    - ``Decision.decision = 'pending'`` (non ancora skip/promote)
    - ``Decision.promotion_state != 'done'`` (auto-hide post-Analizza)

    Restituisce 4 KPI + breakdown:

    - ``pending``: int — offer pending visibili (passano tutti i filtri sopra).
    - ``score_ok``: int — sotto-insieme di ``pending`` con
      ``cv_match_score >= settings.promote_score_threshold``: i meritevoli di
      analisi AI (gate at-ingest passato).
    - ``score_na``: int — sotto-insieme di ``pending`` con ``cv_match_score
      IS NULL`` (vocabolario CV non ha mappato → score non determinabile).
    - ``analyzed_total``: int — contatore vita cumulativo di tutte le offer
      con ``promotion_state = 'done'`` (NON filtrato per pending, è il funnel
      storico /worldwild → Pulse). Non è quindi un sotto-insieme di ``pending``.
    - ``per_source``: dict[str, int] — breakdown ``score_ok`` per sorgente
      (adzuna/remotive/…). Chiavi fisse via ``ALL_SOURCES`` per layout stabile.
    """
    visible_pending = (
        JobOffer.pre_filter_passed.is_(True)
        & (Decision.decision == DECISION_PENDING)
        & (Decision.promotion_state != PROMOTION_STATE_DONE)
    )
    pending = db.execute(
        select(func.count(JobOffer.id)).join(Decision, Decision.job_offer_id == JobOffer.id).where(visible_pending)
    ).scalar_one()
    score_ok = db.execute(
        select(func.count(JobOffer.id))
        .join(Decision, Decision.job_offer_id == JobOffer.id)
        .where(visible_pending & (JobOffer.cv_match_score >= settings.promote_score_threshold))
    ).scalar_one()
    score_na = db.execute(
        select(func.count(JobOffer.id))
        .join(Decision, Decision.job_offer_id == JobOffer.id)
        .where(visible_pending & JobOffer.cv_match_score.is_(None))
    ).scalar_one()
    analyzed_total = db.execute(
        select(func.count(Decision.id)).where(Decision.promotion_state == PROMOTION_STATE_DONE)
    ).scalar_one()
    per_source: dict[str, int] = {}
    for source in ALL_SOURCES:
        cnt = db.execute(
            select(func.count(JobOffer.id))
            .join(Decision, Decision.job_offer_id == JobOffer.id)
            .where(
                visible_pending
                & (JobOffer.cv_match_score >= settings.promote_score_threshold)
                & (JobOffer.source == source)
            )
        ).scalar_one()
        per_source[source] = int(cnt)
    return {
        "pending": int(pending),
        "score_ok": int(score_ok),
        "score_na": int(score_na),
        "analyzed_total": int(analyzed_total),
        "per_source": per_source,
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


def _run_send_to_pulse_in_background(offer_id: UUID, user_id: UUID) -> None:
    """Background task body: apre sessioni fresche su entrambi i DB e spedisce a Pulse.

    Mirror del pattern di ``inbox/routes.py`` (``SessionLocal()`` fresh invece
    di riusare la session della request), col twist cross-DB: la spedizione
    a Pulse necessita la primary (Neon) per leggere il CV + creare JobAnalysis,
    e la secondary (Supabase) per aggiornare la Decision.

    Errori loggati e swallowed — la route ha già ritornato 202 al client,
    re-raise qui inquina solo i log del worker senza informare l'utente.
    Sentry breadcrumb cattura comunque l'eccezione.
    """
    primary_db = PrimarySessionLocal()
    secondary_db = WorldwildSessionLocal() if WorldwildSessionLocal is not None else None
    if secondary_db is None:  # pragma: no cover — gestito prima nella route
        primary_db.close()
        return
    try:
        send_to_pulse(
            primary_db,
            secondary_db,
            offer_id=offer_id,
            user_id=user_id,
        )
        primary_db.commit()
        secondary_db.commit()
    except Exception:
        _logger.exception("worldwild send-to-pulse background task failed (offer=%s)", offer_id)
        primary_db.rollback()
        secondary_db.rollback()
    finally:
        primary_db.close()
        secondary_db.close()


@api_router.post("/analizza/{offer_id}", response_model=PromoteResponse, status_code=202)
def send_offer_to_pulse(
    request: Request,
    offer_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    db: WorldwildDbSession,
    primary_db: DbSession,
    _guard: WorldwildEnabledGuard,
) -> PromoteResponse:
    """Schedula l'analisi AI di una WorldWild offer su Pulse in background.

    Ritorna 202 Accepted subito: il task gira in BackgroundTask con sessioni
    DB fresh — vedi :func:`_run_send_to_pulse_in_background` — perché
    ``run_analysis`` (Anthropic call) è long-running. L'UI pollia o ascolta
    SSE per lo stato terminale su ``Decision.promotion_state``.

    Il task crea una ``JobAnalysis`` su Pulse con i campi AI già popolati
    (score, strengths, gaps, …) e source=``worldwild``. Vedi docstring di
    :func:`services.promote.send_to_pulse` per failure modes / idempotenza.
    """
    try:
        offer_uuid = UUID(offer_id)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid offer_id") from exc

    if db.get(JobOffer, offer_uuid) is None:
        raise HTTPException(status_code=404, detail="JobOffer not found")

    # Detach lo user_id prima di passarlo al background task — il task usa
    # sessioni fresh e non deve dipendere dall'oggetto user della request.
    user_id: UUID = user.id  # type: ignore[assignment]
    background_tasks.add_task(_run_send_to_pulse_in_background, offer_uuid, user_id)

    dual_audit(
        primary_db,
        db,
        request,
        "worldwild_send_to_pulse_scheduled",
        f"offer={offer_id}",
    )
    primary_db.commit()
    db.commit()
    _logger.info("worldwild send-to-pulse scheduled (offer=%s)", offer_uuid)
    return PromoteResponse(
        accepted=True,
        offer_id=str(offer_uuid),
        state="pending",
        message="Send-to-Pulse scheduled — poll Decision.promotion_state for terminal status.",
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


# =============================================================================
# 8 nuove route ingest — una per adapter, no factory generica per scelta Marco.
# Ogni route delega alla propria run_<source>_ingest del modulo services.ingest,
# poi audit dual + commit. Stesso pattern di /ingest/adzuna sopra.
# =============================================================================


def _run_and_audit(
    request: Request,
    db: WorldwildDbSession,
    primary_db: DbSession,
    *,
    source: str,
    run_callable: Any,
) -> IngestResponse:
    """Helper privato: esegue ``run_callable(db)`` + audit dual + commit.

    Centralizza il try/except + dual_audit + commit ripetuto in 9 route.
    Niente factory esposta esternamente: le 9 route restano endpoint distinti.
    """
    try:
        result = run_callable(db)
        db.commit()
    except Exception as exc:  # noqa: BLE001 — surface adapter failure to caller
        _logger.exception("worldwild ingest failed source=%s (type=%s)", source, type(exc).__name__)
        db.rollback()
        raise HTTPException(status_code=502, detail=f"{source} ingest failed") from exc

    dual_audit(
        primary_db,
        db,
        request,
        "worldwild_ingest",
        f"source={source} run={result.run_id} new={result.new}",
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


@api_router.post("/ingest/remotive", response_model=IngestResponse)
def trigger_remotive_ingest(
    request: Request,
    user: CurrentUser,
    db: WorldwildDbSession,
    primary_db: DbSession,
    _guard: WorldwildEnabledGuard,
) -> IngestResponse:
    """Trigger manuale ingest run su Remotive (search-based, no auth)."""
    return _run_and_audit(
        request,
        db,
        primary_db,
        source="remotive",
        run_callable=lambda d: run_remotive_ingest(d, run_type="manual"),
    )


@api_router.post("/ingest/arbeitnow", response_model=IngestResponse)
def trigger_arbeitnow_ingest(
    request: Request,
    user: CurrentUser,
    db: WorldwildDbSession,
    primary_db: DbSession,
    _guard: WorldwildEnabledGuard,
) -> IngestResponse:
    """Trigger manuale ingest run su Arbeitnow (page-based, remote-only filter)."""
    return _run_and_audit(
        request,
        db,
        primary_db,
        source="arbeitnow",
        run_callable=lambda d: run_arbeitnow_ingest(d, run_type="manual"),
    )


@api_router.post("/ingest/jobicy", response_model=IngestResponse)
def trigger_jobicy_ingest(
    request: Request,
    user: CurrentUser,
    db: WorldwildDbSession,
    primary_db: DbSession,
    _guard: WorldwildEnabledGuard,
) -> IngestResponse:
    """Trigger manuale ingest run su Jobicy (single fetch, filtri industry/geo/tag)."""
    return _run_and_audit(
        request,
        db,
        primary_db,
        source="jobicy",
        run_callable=lambda d: run_jobicy_ingest(d, run_type="manual"),
    )


@api_router.post("/ingest/remoteok", response_model=IngestResponse)
def trigger_remoteok_ingest(
    request: Request,
    user: CurrentUser,
    db: WorldwildDbSession,
    primary_db: DbSession,
    _guard: WorldwildEnabledGuard,
) -> IngestResponse:
    """Trigger manuale ingest run su Remote OK (single fetch con tags filter)."""
    return _run_and_audit(
        request,
        db,
        primary_db,
        source="remoteok",
        run_callable=lambda d: run_remoteok_ingest(d, run_type="manual"),
    )


@api_router.post("/ingest/themuse", response_model=IngestResponse)
def trigger_themuse_ingest(
    request: Request,
    user: CurrentUser,
    db: WorldwildDbSession,
    primary_db: DbSession,
    _guard: WorldwildEnabledGuard,
) -> IngestResponse:
    """Trigger manuale ingest run su The Muse (page-based, queries come category)."""
    return _run_and_audit(
        request,
        db,
        primary_db,
        source="themuse",
        run_callable=lambda d: run_themuse_ingest(d, run_type="manual"),
    )


@api_router.post("/ingest/findwork", response_model=IngestResponse)
def trigger_findwork_ingest(
    request: Request,
    user: CurrentUser,
    db: WorldwildDbSession,
    primary_db: DbSession,
    _guard: WorldwildEnabledGuard,
) -> IngestResponse:
    """Trigger manuale ingest run su Findwork (search-based, auth via FINDWORK_API_KEY)."""
    return _run_and_audit(
        request,
        db,
        primary_db,
        source="findwork",
        run_callable=lambda d: run_findwork_ingest(d, run_type="manual"),
    )


@api_router.post("/ingest/workingnomads", response_model=IngestResponse)
def trigger_workingnomads_ingest(
    request: Request,
    user: CurrentUser,
    db: WorldwildDbSession,
    primary_db: DbSession,
    _guard: WorldwildEnabledGuard,
) -> IngestResponse:
    """Trigger manuale ingest run su Working Nomads (single fetch, no auth)."""
    return _run_and_audit(
        request,
        db,
        primary_db,
        source="workingnomads",
        run_callable=lambda d: run_workingnomads_ingest(d, run_type="manual"),
    )


@api_router.post("/ingest/weworkremotely", response_model=IngestResponse)
def trigger_weworkremotely_ingest(
    request: Request,
    user: CurrentUser,
    db: WorldwildDbSession,
    primary_db: DbSession,
    _guard: WorldwildEnabledGuard,
) -> IngestResponse:
    """Trigger manuale ingest run su We Work Remotely (RSS feed)."""
    return _run_and_audit(
        request,
        db,
        primary_db,
        source="weworkremotely",
        run_callable=lambda d: run_weworkremotely_ingest(d, run_type="manual"),
    )
