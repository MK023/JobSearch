"""Promotion pipeline: cross-DB JobAnalysis insert su Pulse (primary).

Flusso semplificato (post audit 4/5):

    JobOffer (visible su /worldwild)
        │
        ▼  Marco preme "Promote" sull'UI
        │
        ▼
    send_to_pulse(offer_id)            ← NESSUNA AI call qui
        │
        ├─ already_done ───────────────► state = done (idempotenza)
        │                                 nessun insert duplicato
        │
        ├─ no active CV ───────────────► state = failed  (retryable)
        │
        └─ insert JobAnalysis su Pulse ► state = done
                                         (status='colloquio',
                                          source='worldwild',
                                          ready-for-review da Marco)

**Nota architetturale:** lo stack-match score è ora calcolato at-ingest
(``JobOffer.cv_match_score``, vedi ``services/ingest.py``), quindi qui non
serve più riapplicare il gate. Pulse esegue la sua analisi AI Anthropic
nel suo flow normale (``/history``, ``/agenda`` Pulse-side) quando Marco
visiona la candidatura promossa: la promozione è una **spedizione**, non
un'analisi.

Cross-DB: la riga ``JobAnalysis`` vive su Pulse (primary, Neon), la riga
``Decision`` vive su WorldWild (secondary, Supabase). Il puntatore
``Decision.promoted_to_neon_id`` è un UUID nudo senza vincolo FK —
Postgres non può enforce FK cross-database. Il caller possiede i commit
su entrambe le sessioni: questa funzione fa solo flush, così un fallimento
parziale rolla back pulito quando il caller rolla back.
"""

from __future__ import annotations

import logging
from typing import NamedTuple
from uuid import UUID

from sqlalchemy.orm import Session

from ...analysis.models import AnalysisSource, AnalysisStatus, JobAnalysis
from ...cv.service import get_latest_cv
from ...notification_center.sse import broadcast_sync
from ..models import (
    PROMOTION_STATE_DONE,
    PROMOTION_STATE_FAILED,
    PROMOTION_STATE_IDLE,
    Decision,
    JobOffer,
)

_logger = logging.getLogger(__name__)


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
) -> PromotionResult:
    """Spedisce una WorldWild offer su Pulse come ``JobAnalysis`` minimal.

    Idempotente: re-run su una Decision già in stato ``done`` ritorna
    immediatamente senza creare duplicati. Per forzare una nuova spedizione
    (es. JobAnalysis cancellata su Pulse), il caller deve invocare
    :func:`reset_promotion_state` prima.

    Differenze chiave vs il vecchio ``run_promotion_analysis``:

    - **Niente Claude call**: l'analisi AI è di Pulse, non di WorldWild.
    - **Niente budget gate**: nessun costo da gatekeepare qui.
    - **Niente score gate**: già applicato at-ingest tramite
      ``JobOffer.cv_match_score``.
    - **Niente add_spending**: nessun token consumato in questo step.

    La JobAnalysis inserita ha:

    - ``status='colloquio'`` — Marco l'ha promossa esplicitamente, la marca
      come "stiamo seguendo" sul funnel Pulse.
    - ``source='worldwild'`` — origine tracciabile per analytics.
    - ``cv_id`` del CV attivo dell'utente.
    - ``job_description``, ``job_url``, ``company``, ``role``, ``location``
      copiati dalla JobOffer; campi AI (score/strengths/gaps/...) vuoti
      finché Pulse non runna la sua analisi.
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

    # 1. Carica la JobOffer source-of-truth per i campi minimal.
    offer = secondary_db.get(JobOffer, offer_id)
    if offer is None:
        raise PromotionGateError(f"JobOffer {offer_id} not found")

    # 2. Active CV su Pulse: la JobAnalysis ha FK a cv_profiles.id.
    cv = get_latest_cv(primary_db, user_id)
    if cv is None:
        return _mark_failed(decision, reason="no_active_cv")

    # 3. Insert minimal JobAnalysis su Pulse. Tutti i campi AI restano
    # vuoti/default: Pulse li popolerà alla prima visione di Marco via
    # /history o /agenda Pulse-side, dove gira analyze_job nel flow standard.
    analysis = JobAnalysis(
        cv_id=cv.id,
        job_description=offer.description or "",
        job_url=offer.url or "",
        company=offer.company or "",
        role=offer.title or "",
        location=offer.location or "",
        salary_info=_format_salary(offer),
        status=AnalysisStatus.INTERVIEW.value,  # 'colloquio': Marco la sta seguendo
        source=AnalysisSource.WORLDWILD.value,
    )
    primary_db.add(analysis)
    primary_db.flush()

    # 4. Aggiorna la Decision con il pointer cross-DB + state done.
    decision.promoted_to_neon_id = analysis.id  # type: ignore[assignment]
    decision.promotion_state = PROMOTION_STATE_DONE  # type: ignore[assignment]
    decision.promotion_error = ""  # type: ignore[assignment]
    secondary_db.flush()

    # Notifica clienti SSE: la state machine ha appena fatto la transizione
    # idle → done (niente più stati intermedi pending/skipped). Il client
    # ricarica lo state via fetch su ricezione dell'evento.
    broadcast_sync("worldwild:promotion_state")

    return PromotionResult(
        state=PROMOTION_STATE_DONE,
        analysis_id=analysis.id,  # type: ignore[arg-type]
        error="",
    )


def _format_salary(offer: JobOffer) -> str:
    """Formatta salary range in stringa human-readable per JobAnalysis.salary_info.

    Best-effort: se mancano i campi, ritorna stringa vuota (Pulse mostrerà
    "n/d" in UI, coerente con il pattern delle altre source).
    """
    smin = offer.salary_min
    smax = offer.salary_max
    cur = offer.salary_currency or ""
    if smin is None and smax is None:
        return ""
    if smin is not None and smax is not None:
        return f"{smin}-{smax} {cur}".strip()
    only = smin if smin is not None else smax
    return f"{only} {cur}".strip()


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
