"""Test idempotenza ``run_promotion_analysis`` sugli stati della state-machine.

Obiettivo: documentare/asserire il comportamento di re-run su una ``Decision``
già lavorata, evitando double-spend involontari della API Claude.

State machine (vedi ``models.PROMOTION_STATE_*``):

- ``idle`` → primo run, gate parte da zero, Claude chiamato se score ≥ threshold.
- ``pending`` → gate riparte (overwrite stato), Claude chiamato di nuovo
  (NB: il gate è deterministico → reset score senza side-effect dannosi).
- ``skipped_low_match`` → terminal ma re-runnabile: il gate ricalcola lo
  stesso score, niente Claude (no double-spend). Comportamento atteso e
  asserito qui.
- ``failed`` → retry permesso: il gate ripassa, Claude tentato di nuovo.
  Coerente con il design (failure è retryable).
- ``done`` → **idempotente**. Il service ha un guard early-return (step 0
  in ``run_promotion_analysis``) che ritorna ``PromotionResult`` con
  ``skipped_reason='already_done'`` senza chiamare il gate né Claude.
  Per forzare un retry pulito, il caller deve invocare
  ``reset_promotion_state()`` che riporta lo state a ``idle``.

Pattern fixture: in-memory SQLite + ``WorldwildBase`` + sample offer/decision,
mock di ``run_analysis`` / ``check_budget_available`` / ``get_latest_cv`` /
``add_spending`` (replica fedele di ``test_worldwild_run_promotion.py``).
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.worldwild_db import WorldwildBase
from src.worldwild import audit_models, models  # noqa: F401  -- register tables
from src.worldwild.models import (
    DECISION_PENDING,
    PROMOTION_STATE_DONE,
    PROMOTION_STATE_FAILED,
    PROMOTION_STATE_IDLE,
    PROMOTION_STATE_PENDING,
    PROMOTION_STATE_SKIPPED_LOW_MATCH,
    Decision,
    JobOffer,
)
from src.worldwild.services.promote import (
    reset_promotion_state,
    run_promotion_analysis,
)

# ── Fixtures (replica del pattern in test_worldwild_run_promotion.py) ──────


@pytest.fixture
def secondary_db() -> Any:
    """Secondary (Supabase-style) in-memory SQLite, bound a WorldwildBase."""
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


@pytest.fixture
def primary_db_mock() -> MagicMock:
    """Stand-in del primary (Neon) — non viene mai toccato sui path skip."""
    return MagicMock(name="primary_db")


# ── Helpers ────────────────────────────────────────────────────────────────


def _seed_high_match_offer(secondary_db: Any) -> UUID:
    """Inserisce JobOffer + Decision in stato pending con stack ad alto match."""
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
    # cast: SQLAlchemy mypy plugin tipizza l'attributo come Column[UUID],
    # ma a runtime è un UUID Python (instance attribute post-flush).
    return cast(UUID, offer.id)


def _seed_low_match_offer(secondary_db: Any) -> UUID:
    """Stack che il gate scarta (sotto threshold)."""
    offer = JobOffer(
        source="adzuna",
        external_id=f"ext-{uuid4().hex[:8]}",
        content_hash=f"hash-{uuid4().hex[:16]}",
        title="Mainframe Specialist",
        company="LegacyCo",
        location="Milano",
        url="https://example.com/job/legacy",
        description="OpenShift Vault OAuth — old stack.",
        pre_filter_passed=True,
    )
    secondary_db.add(offer)
    secondary_db.flush()
    secondary_db.add(Decision(job_offer_id=offer.id, decision=DECISION_PENDING))
    secondary_db.flush()
    return cast(UUID, offer.id)


def _fake_analysis_result() -> dict[str, Any]:
    return {
        "score": 82,
        "recommendation": "candidati",
        "company": "TestCorp",
        "role": "Senior DevOps Engineer",
        "tokens": {"input": 1234, "output": 567},
        "cost_usd": 0.0123,
        "model_used": "claude-haiku-4-5-20251001",
    }


def _set_decision_state(
    secondary_db: Any, offer_id: UUID, *, state: str, promoted_to_neon_id: UUID | None = None
) -> None:
    """Forza la Decision in uno stato arbitrario per i test re-run."""
    decision = secondary_db.query(Decision).filter(Decision.job_offer_id == offer_id).one()
    decision.promotion_state = state
    if promoted_to_neon_id is not None:
        decision.promoted_to_neon_id = promoted_to_neon_id
    secondary_db.flush()


# ── Test class ─────────────────────────────────────────────────────────────


class TestPromotionIdempotency:
    """Re-run di run_promotion_analysis su Decision già lavorate."""

    def test_skipped_low_match_rerun_does_not_call_claude(self, secondary_db: Any, primary_db_mock: MagicMock) -> None:
        """Re-run su skipped_low_match: gate ricalcola, Claude NON chiamato.

        Idempotenza reale (no double-spend): l'offer ha stack a basso match,
        il gate la scarta deterministicamente sia al primo che al secondo run.
        """
        offer_id = _seed_low_match_offer(secondary_db)
        # Primo run → state diventa skipped_low_match
        first = run_promotion_analysis(
            primary_db_mock,
            secondary_db,
            offer_id=offer_id,
            user_id=uuid4(),
        )
        assert first.state == PROMOTION_STATE_SKIPPED_LOW_MATCH

        # Secondo run con run_analysis spiato: NON deve essere chiamato
        with patch("src.worldwild.services.promote.run_analysis") as mock_run:
            second = run_promotion_analysis(
                primary_db_mock,
                secondary_db,
                offer_id=offer_id,
                user_id=uuid4(),
            )
        assert second.state == PROMOTION_STATE_SKIPPED_LOW_MATCH
        assert second.cost_usd == 0.0
        mock_run.assert_not_called()

    def test_failed_state_allows_retry_with_new_claude_call(
        self, secondary_db: Any, primary_db_mock: MagicMock
    ) -> None:
        """Re-run su failed: retry esplicito, gate ripassa, Claude chiamato.

        ``failed`` NON è terminal — il design ammette retry diretto. Il
        secondo run incontra ora budget OK + CV OK e completa con successo.
        """
        offer_id = _seed_high_match_offer(secondary_db)
        # Forziamo lo stato come se un run precedente fosse fallito
        _set_decision_state(secondary_db, offer_id, state=PROMOTION_STATE_FAILED)
        decision = secondary_db.query(Decision).filter(Decision.job_offer_id == offer_id).one()
        decision.promotion_error = "analyzer:RuntimeError"
        secondary_db.flush()

        fake_cv = MagicMock(raw_text="Marco CV", id=uuid4())
        fake_analysis = MagicMock(id=uuid4())
        with (
            patch(
                "src.worldwild.services.promote.check_budget_available",
                return_value=(True, ""),
            ),
            patch(
                "src.worldwild.services.promote.get_latest_cv",
                return_value=fake_cv,
            ),
            patch(
                "src.worldwild.services.promote.run_analysis",
                return_value=(fake_analysis, _fake_analysis_result()),
            ) as mock_run,
            patch("src.worldwild.services.promote.add_spending"),
        ):
            result = run_promotion_analysis(
                primary_db_mock,
                secondary_db,
                offer_id=offer_id,
                user_id=uuid4(),
            )
        assert result.state == PROMOTION_STATE_DONE
        # Il retry HA chiamato Claude (1 volta) — coerente con design
        assert mock_run.call_count == 1
        # Errore precedente ripulito
        decision = secondary_db.query(Decision).filter(Decision.job_offer_id == offer_id).one()
        assert decision.promotion_error == ""

    def test_pending_state_rerun_proceeds_normally(self, secondary_db: Any, primary_db_mock: MagicMock) -> None:
        """Re-run su pending: gate sovrascrive lo stato, Claude chiamato.

        ``pending`` significa "in flight" — non c'è guard contro double-run
        concorrenti. Documentazione del comportamento attuale: il secondo
        run procede e issue una nuova Claude call. Mitigation reale: lock
        a livello UI/cron, non nel service.
        """
        offer_id = _seed_high_match_offer(secondary_db)
        _set_decision_state(secondary_db, offer_id, state=PROMOTION_STATE_PENDING)

        fake_cv = MagicMock(raw_text="Marco CV", id=uuid4())
        fake_analysis = MagicMock(id=uuid4())
        with (
            patch(
                "src.worldwild.services.promote.check_budget_available",
                return_value=(True, ""),
            ),
            patch(
                "src.worldwild.services.promote.get_latest_cv",
                return_value=fake_cv,
            ),
            patch(
                "src.worldwild.services.promote.run_analysis",
                return_value=(fake_analysis, _fake_analysis_result()),
            ) as mock_run,
            patch("src.worldwild.services.promote.add_spending"),
        ):
            result = run_promotion_analysis(
                primary_db_mock,
                secondary_db,
                offer_id=offer_id,
                user_id=uuid4(),
            )
        assert result.state == PROMOTION_STATE_DONE
        assert mock_run.call_count == 1

    def test_reset_then_run_proceeds_with_ai_call(self, secondary_db: Any, primary_db_mock: MagicMock) -> None:
        """``reset_promotion_state`` + run: state torna idle e Claude parte.

        È il path "ufficiale" del docstring per forzare il retry pulito
        dopo un done: caller chiama reset, poi run_promotion_analysis.
        """
        offer_id = _seed_high_match_offer(secondary_db)
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

        # Re-run dopo reset → Claude chiamato esattamente 1 volta
        fake_cv = MagicMock(raw_text="Marco CV", id=uuid4())
        fake_analysis = MagicMock(id=uuid4())
        with (
            patch(
                "src.worldwild.services.promote.check_budget_available",
                return_value=(True, ""),
            ),
            patch(
                "src.worldwild.services.promote.get_latest_cv",
                return_value=fake_cv,
            ),
            patch(
                "src.worldwild.services.promote.run_analysis",
                return_value=(fake_analysis, _fake_analysis_result()),
            ) as mock_run,
            patch("src.worldwild.services.promote.add_spending"),
        ):
            result = run_promotion_analysis(
                primary_db_mock,
                secondary_db,
                offer_id=offer_id,
                user_id=uuid4(),
            )
        assert result.state == PROMOTION_STATE_DONE
        assert mock_run.call_count == 1

    def test_skipped_low_match_rerun_preserves_score_no_neon_writes(
        self, secondary_db: Any, primary_db_mock: MagicMock
    ) -> None:
        """Re-run skipped: invariante secondaria — primary_db mai toccato.

        Difesa-in-profondità: anche se in futuro qualcuno cambia il flow,
        un offer sotto threshold non deve mai produrre side-effect sul
        primary (no JobAnalysis, no budget ledger update).
        """
        offer_id = _seed_low_match_offer(secondary_db)
        run_promotion_analysis(
            primary_db_mock,
            secondary_db,
            offer_id=offer_id,
            user_id=uuid4(),
        )
        # Reset dei contatori del mock prima del secondo giro
        primary_db_mock.reset_mock()

        run_promotion_analysis(
            primary_db_mock,
            secondary_db,
            offer_id=offer_id,
            user_id=uuid4(),
        )
        primary_db_mock.query.assert_not_called()
        primary_db_mock.add.assert_not_called()
        primary_db_mock.commit.assert_not_called()

    def test_done_state_rerun_short_circuits_no_claude_call(
        self, secondary_db: Any, primary_db_mock: MagicMock
    ) -> None:
        """Re-run su ``done``: short-circuit, Claude NON chiamato.

        Caso critico anti double-spend: il service ha un guard early-return
        (step 0 in ``run_promotion_analysis``) che, se la decision è già
        ``done``, ritorna immediatamente ``PromotionResult`` con
        ``skipped_reason='already_done'`` e ``cost_usd=0.0``, preservando
        ``promoted_to_neon_id``. Né il gate né Claude vengono toccati.
        """
        offer_id = _seed_high_match_offer(secondary_db)
        old_neon_id = uuid4()
        _set_decision_state(
            secondary_db,
            offer_id,
            state=PROMOTION_STATE_DONE,
            promoted_to_neon_id=old_neon_id,
        )
        # Forziamo anche uno score precedente per verificare che il
        # short-circuit lo rispedisca al chiamante invariato.
        decision_before = secondary_db.query(Decision).filter(Decision.job_offer_id == offer_id).one()
        decision_before.promotion_score = 87
        secondary_db.flush()

        with (
            patch("src.worldwild.services.promote.run_analysis") as mock_run,
            patch("src.worldwild.services.promote.evaluate_for_promotion") as mock_gate,
            patch("src.worldwild.services.promote.check_budget_available") as mock_budget,
        ):
            result = run_promotion_analysis(
                primary_db_mock,
                secondary_db,
                offer_id=offer_id,
                user_id=uuid4(),
            )
        # Invariante anti double-spend:
        mock_run.assert_not_called()
        # Anche il gate viene saltato (short-circuit precoce)
        mock_gate.assert_not_called()
        # Né viene letto il budget ledger
        mock_budget.assert_not_called()

        # Risultato esposto al caller
        assert result.state == PROMOTION_STATE_DONE
        assert result.cost_usd == 0.0
        assert result.error == ""
        assert result.skipped_reason == "already_done"
        assert result.score == 87
        assert result.analysis_id == old_neon_id

        # State persistito non viene modificato dal short-circuit
        decision_after = secondary_db.query(Decision).filter(Decision.job_offer_id == offer_id).one()
        assert decision_after.promotion_state == PROMOTION_STATE_DONE
        assert decision_after.promoted_to_neon_id == old_neon_id
