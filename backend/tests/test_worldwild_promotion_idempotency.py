"""Test idempotenza ``send_to_pulse`` sugli stati della state-machine.

Obiettivo: documentare/asserire il comportamento di re-run su una ``Decision``
già lavorata, evitando insert duplicati di JobAnalysis su Pulse.

State machine (vedi ``models.PROMOTION_STATE_*``):

- ``idle`` → primo run, JobAnalysis creata su Pulse, transizione a ``done``.
- ``failed`` → retry permesso: il flow ripassa, nuovo tentativo. Coerente
  con il design (failure è retryable, es. CV mancante poi caricato).
- ``done`` → **idempotente**. Il service ha un guard early-return (step 0
  in ``send_to_pulse``) che ritorna ``PromotionResult`` con
  ``skipped_reason='already_done'`` senza creare duplicati. Per forzare
  un retry pulito, il caller deve invocare ``reset_promotion_state()``
  che riporta lo state a ``idle``.

``run_analysis`` (chiamata Anthropic) è mockata: la firma + l'effetto
collaterale di insert su primary_db sono identici al flow reale, ma niente
HTTP call.
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analysis.models import JobAnalysis
from src.database.base import Base
from src.database.worldwild_db import WorldwildBase
from src.worldwild import audit_models, models  # noqa: F401  -- register tables
from src.worldwild.models import (
    DECISION_PENDING,
    PROMOTION_STATE_DONE,
    PROMOTION_STATE_FAILED,
    PROMOTION_STATE_IDLE,
    Decision,
    JobOffer,
)
from src.worldwild.services.promote import (
    reset_promotion_state,
    send_to_pulse,
)

# Importa i modelli Base per registrarli prima di create_all sul primary.
from tests.conftest import _ALL_MODELS  # noqa: F401

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def primary_db() -> Any:
    """Primary in-memory SQLite (Pulse / Neon-equivalent)."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def secondary_db() -> Any:
    """Secondary in-memory SQLite (WorldWild / Supabase-equivalent)."""
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


# ── Helpers ────────────────────────────────────────────────────────────────


def _seed_offer(secondary_db: Any) -> UUID:
    """Inserisce JobOffer + Decision in stato pending."""
    offer = JobOffer(
        source="adzuna",
        external_id=f"ext-{uuid4().hex[:8]}",
        content_hash=f"hash-{uuid4().hex[:16]}",
        title="Senior DevOps Engineer",
        company="TestCorp",
        location="Milano",
        url="https://example.com/job/idem",
        description="Python, Kubernetes, AWS, Terraform — full remote.",
        pre_filter_passed=True,
    )
    secondary_db.add(offer)
    secondary_db.flush()
    secondary_db.add(Decision(job_offer_id=offer.id, decision=DECISION_PENDING))
    secondary_db.flush()
    return cast(UUID, offer.id)


def _set_decision_state(
    secondary_db: Any, offer_id: UUID, *, state: str, promoted_to_neon_id: UUID | None = None
) -> None:
    """Forza la Decision in uno stato arbitrario per i test re-run."""
    decision = secondary_db.query(Decision).filter(Decision.job_offer_id == offer_id).one()
    decision.promotion_state = state
    if promoted_to_neon_id is not None:
        decision.promoted_to_neon_id = promoted_to_neon_id
    secondary_db.flush()


def _fake_run_analysis_factory(primary_db: Any, cv_id: UUID) -> Any:
    """Mocka ``run_analysis`` riproducendo l'effetto di insert + return."""

    def _fake(
        db: Any,
        cv_text: str,
        cv_id_arg: UUID,
        job_description: str,
        job_url: str,
        model: str,
        cache: Any = None,
        user_id: Any = None,
        source: str = "manual",
    ) -> tuple[JobAnalysis, dict[str, Any]]:
        analysis = JobAnalysis(
            cv_id=cv_id_arg,
            job_description=job_description or "stub",
            job_url=job_url,
            company="TestCorp",
            role="Senior DevOps Engineer",
            score=80,
            source=source,
        )
        primary_db.add(analysis)
        primary_db.flush()
        return analysis, {"cost_usd": 0.01, "tokens": {"input": 100, "output": 50}}

    return _fake


# ── Test class ─────────────────────────────────────────────────────────────


class TestSendToPulseIdempotency:
    """Re-run di send_to_pulse su Decision già lavorate."""

    def test_done_state_rerun_short_circuits_no_duplicate_insert(self, primary_db: Any, secondary_db: Any) -> None:
        """Re-run su ``done``: short-circuit, niente JobAnalysis duplicata.

        Caso critico anti-duplicazione: il service ha un guard early-return
        che, se la decision è già ``done``, ritorna immediatamente
        ``PromotionResult`` con ``skipped_reason='already_done'`` preservando
        ``promoted_to_neon_id``. Né get_latest_cv né l'insert vengono toccati.
        """
        offer_id = _seed_offer(secondary_db)
        old_neon_id = uuid4()
        _set_decision_state(
            secondary_db,
            offer_id,
            state=PROMOTION_STATE_DONE,
            promoted_to_neon_id=old_neon_id,
        )

        with patch("src.worldwild.services.promote.get_latest_cv") as mock_cv:
            result = send_to_pulse(
                primary_db,
                secondary_db,
                offer_id=offer_id,
                user_id=uuid4(),
            )
        # Invariante anti-duplicazione: CV pipeline non toccato
        mock_cv.assert_not_called()

        # Risultato esposto al caller
        assert result.state == PROMOTION_STATE_DONE
        assert result.error == ""
        assert result.skipped_reason == "already_done"
        assert result.analysis_id == old_neon_id

        # State persistito non viene modificato dal short-circuit
        decision_after = secondary_db.query(Decision).filter(Decision.job_offer_id == offer_id).one()
        assert decision_after.promotion_state == PROMOTION_STATE_DONE
        assert decision_after.promoted_to_neon_id == old_neon_id

        # Nessuna JobAnalysis inserita su primary (short-circuit ha evitato l'insert)
        assert primary_db.query(JobAnalysis).count() == 0

    def test_failed_state_allows_retry_with_new_insert(self, primary_db: Any, secondary_db: Any) -> None:
        """Re-run su failed: retry esplicito, nuovo tentativo di insert.

        ``failed`` NON è terminal — il design ammette retry diretto. Il
        secondo run incontra ora CV OK e completa con successo.
        """
        offer_id = _seed_offer(secondary_db)
        # Forziamo lo stato come se un run precedente fosse fallito (no CV)
        _set_decision_state(secondary_db, offer_id, state=PROMOTION_STATE_FAILED)
        decision = secondary_db.query(Decision).filter(Decision.job_offer_id == offer_id).one()
        decision.promotion_error = "no_active_cv"
        secondary_db.flush()

        cv_id = uuid4()
        fake_cv = MagicMock(id=cv_id, raw_text="cv body")
        with (
            patch("src.worldwild.services.promote.get_latest_cv", return_value=fake_cv),
            patch("src.worldwild.services.promote.check_budget_available", return_value=(True, "")),
            patch(
                "src.worldwild.services.promote.analyze_and_charge",
                side_effect=_fake_run_analysis_factory(primary_db, cv_id),
            ),
        ):
            result = send_to_pulse(
                primary_db,
                secondary_db,
                offer_id=offer_id,
                user_id=uuid4(),
            )
        assert result.state == PROMOTION_STATE_DONE
        # Errore precedente ripulito
        decision = secondary_db.query(Decision).filter(Decision.job_offer_id == offer_id).one()
        assert decision.promotion_error == ""
        # JobAnalysis inserita stavolta
        assert primary_db.query(JobAnalysis).count() == 1

    def test_reset_then_run_proceeds_with_new_insert(self, primary_db: Any, secondary_db: Any) -> None:
        """``reset_promotion_state`` + run: state torna idle, insert procede.

        È il path "ufficiale" per forzare il retry pulito dopo un done:
        caller chiama reset, poi send_to_pulse.
        """
        offer_id = _seed_offer(secondary_db)
        # Simula uno stato done arrivato da un run precedente
        old_neon_id = uuid4()
        _set_decision_state(
            secondary_db,
            offer_id,
            state=PROMOTION_STATE_DONE,
            promoted_to_neon_id=old_neon_id,
        )

        # Reset esplicito → state torna idle
        reset_promotion_state(secondary_db, offer_id=offer_id)
        decision = secondary_db.query(Decision).filter(Decision.job_offer_id == offer_id).one()
        assert decision.promotion_state == PROMOTION_STATE_IDLE
        assert decision.promotion_score is None

        # Re-run dopo reset → nuovo insert su Pulse
        cv_id = uuid4()
        fake_cv = MagicMock(id=cv_id, raw_text="cv body")
        with (
            patch("src.worldwild.services.promote.get_latest_cv", return_value=fake_cv),
            patch("src.worldwild.services.promote.check_budget_available", return_value=(True, "")),
            patch(
                "src.worldwild.services.promote.analyze_and_charge",
                side_effect=_fake_run_analysis_factory(primary_db, cv_id),
            ),
        ):
            result = send_to_pulse(
                primary_db,
                secondary_db,
                offer_id=offer_id,
                user_id=uuid4(),
            )
        assert result.state == PROMOTION_STATE_DONE
        assert result.analysis_id != old_neon_id  # nuovo UUID
        # JobAnalysis presente su Pulse (nuova, dato che reset non cancella la vecchia)
        assert primary_db.query(JobAnalysis).count() == 1
