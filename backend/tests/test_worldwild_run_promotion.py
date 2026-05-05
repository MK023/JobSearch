"""Test end-to-end della spedizione a Pulse (cross-DB JobAnalysis insert).

Mocka ``get_latest_cv`` per non dipendere dal CV pipeline reale; il primary
DB è un in-memory SQLite reale legato a ``Base`` (così la JobAnalysis viene
realmente inserita e si possono fare query). La secondary è un altro
in-memory SQLite legato a ``WorldwildBase``.

Niente Claude qui — il vecchio path AI è stato rimosso (l'analisi AI è di
Pulse, non di WorldWild).
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analysis.models import AnalysisSource, AnalysisStatus, JobAnalysis
from src.database.base import Base
from src.database.worldwild_db import WorldwildBase
from src.worldwild import audit_models, models  # noqa: F401  -- register tables
from src.worldwild.models import (
    DECISION_PENDING,
    PROMOTION_STATE_DONE,
    PROMOTION_STATE_FAILED,
    Decision,
    JobOffer,
)
from src.worldwild.services.promote import send_to_pulse

# Importa i modelli Base per registrarli prima di create_all sul primary.
from tests.conftest import _ALL_MODELS  # noqa: F401


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


def _seed_offer(secondary_db: Any) -> UUID:
    """Inserisce JobOffer + Decision pending nel secondary."""
    offer = JobOffer(
        source="adzuna",
        external_id=f"ext-{uuid4().hex[:8]}",
        content_hash=f"hash-{uuid4().hex[:16]}",
        title="Senior DevOps Engineer",
        company="TestCorp",
        location="Milano",
        url="https://example.com/job/1",
        description="Python, Kubernetes, AWS, Terraform — full remote.",
        salary_min=50000,
        salary_max=70000,
        salary_currency="EUR",
        pre_filter_passed=True,
    )
    secondary_db.add(offer)
    secondary_db.flush()
    secondary_db.add(Decision(job_offer_id=offer.id, decision=DECISION_PENDING))
    secondary_db.flush()
    # cast: SQLAlchemy mypy plugin tipizza l'attributo come Column[UUID],
    # ma a runtime è un UUID Python (instance attribute post-flush).
    return cast(UUID, offer.id)


class TestSendToPulse:
    """Happy path + failure paths della spedizione."""

    def test_happy_path_inserts_job_analysis_on_pulse(self, primary_db: Any, secondary_db: Any) -> None:
        offer_id = _seed_offer(secondary_db)
        fake_cv = MagicMock(id=uuid4())
        with patch("src.worldwild.services.promote.get_latest_cv", return_value=fake_cv):
            result = send_to_pulse(
                primary_db,
                secondary_db,
                offer_id=offer_id,
                user_id=uuid4(),
            )

        assert result.state == PROMOTION_STATE_DONE
        assert result.analysis_id is not None
        assert result.error == ""

        # JobAnalysis presente su primary con campi minimal
        analysis = primary_db.query(JobAnalysis).filter(JobAnalysis.id == result.analysis_id).one()
        assert analysis.cv_id == fake_cv.id
        assert analysis.company == "TestCorp"
        assert analysis.role == "Senior DevOps Engineer"
        assert analysis.location == "Milano"
        assert analysis.job_url == "https://example.com/job/1"
        assert analysis.status == AnalysisStatus.INTERVIEW.value
        assert analysis.source == AnalysisSource.WORLDWILD.value
        # Nessuno score AI: la promozione NON chiama Claude
        assert analysis.score == 0
        # Salary range concatenato in salary_info
        assert "50000" in analysis.salary_info and "70000" in analysis.salary_info

        # Decision aggiornata col puntatore cross-DB
        decision = secondary_db.query(Decision).filter(Decision.job_offer_id == offer_id).one()
        assert decision.promotion_state == PROMOTION_STATE_DONE
        assert decision.promoted_to_neon_id == result.analysis_id

    def test_no_active_cv_marks_failed(self, primary_db: Any, secondary_db: Any) -> None:
        offer_id = _seed_offer(secondary_db)
        with patch("src.worldwild.services.promote.get_latest_cv", return_value=None):
            result = send_to_pulse(
                primary_db,
                secondary_db,
                offer_id=offer_id,
                user_id=uuid4(),
            )
        assert result.state == PROMOTION_STATE_FAILED
        assert result.error == "no_active_cv"

        decision = secondary_db.query(Decision).filter(Decision.job_offer_id == offer_id).one()
        assert decision.promotion_state == PROMOTION_STATE_FAILED
        assert "no_active_cv" in decision.promotion_error
        # Nessuna JobAnalysis inserita
        assert primary_db.query(JobAnalysis).count() == 0

    def test_already_done_short_circuits(self, primary_db: Any, secondary_db: Any) -> None:
        """Idempotenza: re-run su Decision già done non crea duplicati."""
        offer_id = _seed_offer(secondary_db)
        fake_cv = MagicMock(id=uuid4())

        with patch("src.worldwild.services.promote.get_latest_cv", return_value=fake_cv):
            first = send_to_pulse(
                primary_db,
                secondary_db,
                offer_id=offer_id,
                user_id=uuid4(),
            )
        assert first.state == PROMOTION_STATE_DONE
        first_analysis_id = first.analysis_id

        # Re-run: la guard early-return deve evitare un secondo insert
        with patch("src.worldwild.services.promote.get_latest_cv") as mock_cv:
            second = send_to_pulse(
                primary_db,
                secondary_db,
                offer_id=offer_id,
                user_id=uuid4(),
            )
        assert second.state == PROMOTION_STATE_DONE
        assert second.skipped_reason == "already_done"
        assert second.analysis_id == first_analysis_id
        # Il CV pipeline NON è stato toccato (short-circuit precoce)
        mock_cv.assert_not_called()
        # Una sola JobAnalysis presente
        assert primary_db.query(JobAnalysis).count() == 1
