"""Promotion pipeline: cross-DB JobAnalysis insert su Pulse (primary).

Flusso (post sessione 5/5):

    JobOffer (visible su /worldwild)
        │
        ▼  Marco preme "Analizza" sull'UI
        │
        ▼
    send_to_pulse(offer_id)
        │
        ├─ already_done ───────────────► state = done (idempotenza)
        │                                 nessun insert duplicato
        │
        ├─ no active CV ───────────────► state = failed  (retryable)
        │
        ├─ no_budget ─────────────────► state = failed  (retryable)
        │
        ├─ ai_error ──────────────────► state = failed  (retryable)
        │
        └─ run_analysis (Claude) ─────► state = done
                                         JobAnalysis su Pulse popolata
                                         (score/strengths/gaps/...),
                                         status='da_valutare',
                                         source='worldwild'

**Nota architetturale:** lo stack-match score è già calcolato at-ingest
(``JobOffer.cv_match_score``, vedi ``services/ingest.py``) come pre-filtro
gratuito; serve a evitare di chiamare Claude su offerte sotto-soglia. Qui
runniamo l'analisi Anthropic completa: la "spedizione a Pulse" è
un'**analisi end-to-end**, non un placeholder vuoto.

Cross-DB: la riga ``JobAnalysis`` vive su Pulse (primary), la riga
``Decision`` vive su WorldWild (secondary). Il puntatore
``Decision.promoted_to_neon_id`` è un UUID nudo senza vincolo FK —
Postgres non può enforce FK cross-database. Il caller possiede i commit
su entrambe le sessioni: questa funzione fa solo flush, così un fallimento
parziale rolla back pulito quando il caller rolla back.
"""

from __future__ import annotations

import logging
from typing import NamedTuple, cast
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session

from ...analysis.models import AnalysisSource
from ...analysis.service import analyze_and_charge, find_by_url
from ...cv.service import get_latest_cv
from ...dashboard.service import check_budget_available
from ...integrations.cache import CacheService
from ...notification_center.sse import broadcast_sync
from ..models import (
    PROMOTION_STATE_DONE,
    PROMOTION_STATE_FAILED,
    PROMOTION_STATE_IDLE,
    PROMOTION_STATE_PENDING,
    Decision,
    JobOffer,
)

_logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "haiku"  # cost-efficient: stessa scelta del flow extension/cowork


class PromotionGateError(Exception):
    """Sollevato quando l'offer o la sua Decision row non sono caricabili."""


class PromotionResult(NamedTuple):
    """Esito della spedizione a Pulse. Il caller la rende su UI / API."""

    state: str  # uno fra PROMOTION_STATE_* (DONE / FAILED in questo flow)
    analysis_id: UUID | None  # JobAnalysis.id su Pulse, quando state == done
    error: str  # ragione corta quando state == failed
    # Motivo no-op quando saltiamo la spedizione senza errori (es.
    # "already_done" per idempotenza). Vuoto in tutti gli altri casi.
    skipped_reason: str = ""


def reset_promotion_state(db: Session, *, offer_id: UUID) -> None:
    """Reset dei campi di promozione di una Decision back to idle.

    Utile quando Marco cambia idea e re-clicca Promote: vogliamo lavagna
    pulita. Il caller possiede il commit.
    """
    decision = db.query(Decision).filter(Decision.job_offer_id == offer_id).one_or_none()
    if decision is None:
        raise PromotionGateError(f"Decision row for offer {offer_id} not found")
    decision.promotion_state = PROMOTION_STATE_IDLE  # type: ignore[assignment]
    decision.promotion_score = None  # type: ignore[assignment]
    decision.promotion_started_at = None  # type: ignore[assignment]
    decision.promotion_error = ""  # type: ignore[assignment]
    db.flush()


def send_to_pulse(
    primary_db: Session,
    secondary_db: Session,
    *,
    offer_id: UUID,
    user_id: UUID,
    cache: CacheService | None = None,
    model: str = _DEFAULT_MODEL,
) -> PromotionResult:
    """Analizza una WorldWild offer e ne crea la ``JobAnalysis`` su Pulse.

    Idempotente: re-run su una Decision già in stato ``done`` ritorna
    immediatamente senza ri-pagare la chiamata Claude. Per forzare una nuova
    analisi (es. JobAnalysis cancellata su Pulse), il caller deve invocare
    :func:`reset_promotion_state` prima.

    La JobAnalysis prodotta ha:

    - **AI fields popolati**: ``score``, ``strengths``, ``gaps``,
      ``recommendation``, ``career_track``, ecc., calcolati da Anthropic
      tramite :func:`analysis.service.run_analysis` come per il flow
      cowork/extension.
    - ``source='worldwild'`` — origine tracciabile per analytics.
    - ``status`` default (``'da_valutare'``) settato da
      ``run_analysis`` → Marco decide manualmente promozione/scarto.

    Failure modes (state transition → ``failed``, retryable via reset):

    - ``no_active_cv``: l'utente non ha un CV su Pulse.
    - ``no_budget``: budget mensile esaurito (vedi ``check_budget_available``).
    - ``ai_error``: eccezione durante la chiamata Anthropic.
    """
    # 0. Idempotenza: se la Decision è già "done", short-circuit.
    decision = secondary_db.query(Decision).filter(Decision.job_offer_id == offer_id).one_or_none()
    if decision is None:
        raise PromotionGateError(
            f"Decision row for offer {offer_id} not found — expected one to be created at ingest time"
        )
    if decision.promotion_state == PROMOTION_STATE_DONE:
        return PromotionResult(
            state=PROMOTION_STATE_DONE,
            analysis_id=decision.promoted_to_neon_id,  # type: ignore[arg-type]
            error="",
            skipped_reason="already_done",
        )

    # 0b. Atomic claim: prima di partire con la chiamata Anthropic (~10-30s),
    # transitiamo lo stato da idle/failed → pending con UPDATE conditional.
    # Se due concorrenti (UI double-click + retry BG) entrano insieme, solo
    # il primo cambia rowcount=1, il secondo finisce a 0 e short-circuita.
    # Evita doppia chiamata Anthropic + JobAnalysis duplicata su Pulse.
    claim_result = secondary_db.execute(
        update(Decision)
        .where(
            (Decision.job_offer_id == offer_id)
            & (Decision.promotion_state.in_([PROMOTION_STATE_IDLE, PROMOTION_STATE_FAILED]))
        )
        .values(promotion_state=PROMOTION_STATE_PENDING)
    )
    if cast(int, getattr(claim_result, "rowcount", 0)) == 0:
        # Un altro caller ha già preso il lock (state pending) → no-op.
        secondary_db.refresh(decision)
        return PromotionResult(
            state=str(decision.promotion_state or PROMOTION_STATE_PENDING),
            analysis_id=decision.promoted_to_neon_id,  # type: ignore[arg-type]
            error="",
            skipped_reason="claim_lost",
        )
    secondary_db.flush()
    secondary_db.refresh(decision)

    # 1. Carica la JobOffer source-of-truth.
    offer = secondary_db.get(JobOffer, offer_id)
    if offer is None:
        raise PromotionGateError(f"JobOffer {offer_id} not found")

    # 2. Active CV su Pulse: la JobAnalysis ha FK a cv_profiles.id.
    cv = get_latest_cv(primary_db, user_id)
    if cv is None:
        return _mark_failed(decision, reason="no_active_cv")

    # 3. Budget gate (stesso check che applicano /analyze e inbox).
    budget_ok, budget_msg = check_budget_available(primary_db)
    if not budget_ok:
        return _mark_failed(decision, reason=f"no_budget: {budget_msg}")

    # cast espliciti: SQLAlchemy 2.x tipizza Column come ``Column[str] | str``,
    # ma a runtime sono str dopo il flush — vedi readability-first preferenza
    # vs ``# type: ignore`` (best-practice).
    job_description: str = str(offer.description or "")
    job_url: str = str(offer.url or "")

    # 4. URL dedup: se un'altra source ha già analizzato lo stesso URL,
    # riusa la JobAnalysis esistente — niente Claude call duplicata.
    if job_url:
        existing = find_by_url(primary_db, job_url)
        if existing is not None:
            decision.promoted_to_neon_id = existing.id  # type: ignore[assignment]
            decision.promotion_state = PROMOTION_STATE_DONE  # type: ignore[assignment]
            decision.promotion_error = ""  # type: ignore[assignment]
            secondary_db.flush()
            broadcast_sync("worldwild:promotion_state")
            return PromotionResult(
                state=PROMOTION_STATE_DONE,
                analysis_id=existing.id,  # type: ignore[arg-type]
                error="",
                skipped_reason="url_dedup",
            )

    # 5. Run AI analysis + ledger sync via helper centralizzato (vedi
    # ``analysis.service.analyze_and_charge``). Wrap in try/except così un
    # timeout / quota error non lascia la Decision pendente — la marchiamo
    # failed e Marco può riprovare dopo.
    try:
        analysis, _result = analyze_and_charge(
            primary_db,
            cast(str, cv.raw_text),
            cast(UUID, cv.id),
            job_description,
            job_url,
            model,
            cache,
            user_id=user_id,
            source=AnalysisSource.WORLDWILD.value,
        )
    except Exception as exc:  # noqa: BLE001 — graceful failure, error finisce sulla decision
        _logger.warning("send_to_pulse AI call failed for offer %s: %s", offer_id, exc)
        return _mark_failed(decision, reason=f"ai_error: {exc}"[:500])

    # 6. Aggiorna la Decision con il pointer cross-DB + state done.
    decision.promoted_to_neon_id = analysis.id  # type: ignore[assignment]
    decision.promotion_state = PROMOTION_STATE_DONE  # type: ignore[assignment]
    decision.promotion_error = ""  # type: ignore[assignment]
    secondary_db.flush()

    # Notifica clienti SSE: la state machine ha fatto idle → done; il client
    # ricarica lo state e i count della sidebar via fetch sull'evento.
    broadcast_sync("worldwild:promotion_state")

    return PromotionResult(
        state=PROMOTION_STATE_DONE,
        analysis_id=analysis.id,  # type: ignore[arg-type]
        error="",
    )


def _mark_failed(decision: Decision, *, reason: str) -> PromotionResult:
    """Imposta la decision a ``failed`` con ragione corta; flush al caller."""
    decision.promotion_state = PROMOTION_STATE_FAILED  # type: ignore[assignment]
    decision.promotion_error = reason[:500]  # type: ignore[assignment]
    # Notifica SSE: transizione → failed (no active CV)
    broadcast_sync("worldwild:promotion_state")
    return PromotionResult(
        state=PROMOTION_STATE_FAILED,
        analysis_id=None,
        error=reason,
    )
