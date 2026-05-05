"""Test end-to-end della spedizione a Pulse (cross-DB JobAnalysis insert).

Mocka ``get_latest_cv`` + ``run_analysis`` + ``check_budget_available`` per
non dipendere dal CV pipeline reale né da Anthropic; il primary DB è un
in-memory SQLite reale legato a ``Base`` (così la JobAnalysis viene
realmente inserita e si possono fare query). La secondary è un altro
in-memory SQLite legato a ``WorldwildBase``.
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analysis.models import AnalysisSource, JobAnalysis
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
    """Primary in-memory SQLite (Pulse-equivalent)."""
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
    """Secondary in-memory SQLite (WorldWild-equivalent)."""
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
    return cast(UUID, offer.id)


def _fake_run_analysis_factory(primary_db: Any, cv_id: UUID) -> Any:
    """Restituisce una callable che simula ``run_analysis``: insert una
    JobAnalysis con campi AI popolati e ritorna ``(analysis, result_dict)``."""

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
            job_description=job_description,
            job_url=job_url,
            company="TestCorp",
            role="Senior DevOps Engineer",
            location="Milano",
            score=82,
            recommendation="apply",
            strengths=["Python", "Kubernetes"],
            gaps=["Terraform deep"],
            source=source,
        )
        primary_db.add(analysis)
        primary_db.flush()
        return analysis, {
            "cost_usd": 0.012,
            "tokens": {"input": 1500, "output": 800},
            "score": 82,
        }

    return _fake


class TestSendToPulse:
    """Happy path + failure paths della spedizione."""

    def test_happy_path_runs_ai_and_links_decision(self, primary_db: Any, secondary_db: Any) -> None:
        offer_id = _seed_offer(secondary_db)
        cv_id = uuid4()
        fake_cv = MagicMock(id=cv_id, raw_text="cv text body")

        with (
            patch("src.worldwild.services.promote.get_latest_cv", return_value=fake_cv),
            patch("src.worldwild.services.promote.check_budget_available", return_value=(True, "")),
            patch(
                "src.worldwild.services.promote.analyze_and_charge",
                side_effect=_fake_run_analysis_factory(primary_db, cv_id),
            ) as mock_run,
        ):
            result = send_to_pulse(
                primary_db,
                secondary_db,
                offer_id=offer_id,
                user_id=uuid4(),
            )

        assert result.state == PROMOTION_STATE_DONE
        assert result.analysis_id is not None
        assert result.error == ""

        # analyze_and_charge è stata chiamata col source corretto
        kwargs = mock_run.call_args.kwargs
        assert kwargs["source"] == AnalysisSource.WORLDWILD.value

        # JobAnalysis presente su primary con campi AI popolati
        analysis = primary_db.query(JobAnalysis).filter(JobAnalysis.id == result.analysis_id).one()
        assert analysis.cv_id == cv_id
        assert analysis.score == 82
        assert analysis.source == AnalysisSource.WORLDWILD.value

        # Decision aggiornata col puntatore cross-DB
        decision = secondary_db.query(Decision).filter(Decision.job_offer_id == offer_id).one()
        assert decision.promotion_state == PROMOTION_STATE_DONE
        assert decision.promoted_to_neon_id == result.analysis_id

    def test_no_active_cv_marks_failed(self, primary_db: Any, secondary_db: Any) -> None:
        offer_id = _seed_offer(secondary_db)
        with (
            patch("src.worldwild.services.promote.get_latest_cv", return_value=None),
            patch("src.worldwild.services.promote.analyze_and_charge") as mock_run,
        ):
            result = send_to_pulse(
                primary_db,
                secondary_db,
                offer_id=offer_id,
                user_id=uuid4(),
            )
        assert result.state == PROMOTION_STATE_FAILED
        assert result.error == "no_active_cv"
        # AI non è stata invocata se manca il CV
        mock_run.assert_not_called()

        decision = secondary_db.query(Decision).filter(Decision.job_offer_id == offer_id).one()
        assert decision.promotion_state == PROMOTION_STATE_FAILED
        assert "no_active_cv" in decision.promotion_error
        assert primary_db.query(JobAnalysis).count() == 0

    def test_no_budget_marks_failed(self, primary_db: Any, secondary_db: Any) -> None:
        """Budget esaurito → no AI call, decision failed."""
        offer_id = _seed_offer(secondary_db)
        fake_cv = MagicMock(id=uuid4(), raw_text="cv")
        with (
            patch("src.worldwild.services.promote.get_latest_cv", return_value=fake_cv),
            patch(
                "src.worldwild.services.promote.check_budget_available",
                return_value=(False, "monthly cap reached"),
            ),
            patch("src.worldwild.services.promote.analyze_and_charge") as mock_run,
        ):
            result = send_to_pulse(
                primary_db,
                secondary_db,
                offer_id=offer_id,
                user_id=uuid4(),
            )
        assert result.state == PROMOTION_STATE_FAILED
        assert "no_budget" in result.error
        mock_run.assert_not_called()

    def test_ai_error_marks_failed(self, primary_db: Any, secondary_db: Any) -> None:
        """Eccezione Anthropic → decision failed, retryable."""
        offer_id = _seed_offer(secondary_db)
        fake_cv = MagicMock(id=uuid4(), raw_text="cv")
        with (
            patch("src.worldwild.services.promote.get_latest_cv", return_value=fake_cv),
            patch("src.worldwild.services.promote.check_budget_available", return_value=(True, "")),
            patch("src.worldwild.services.promote.analyze_and_charge", side_effect=RuntimeError("anthropic 503")),
        ):
            result = send_to_pulse(
                primary_db,
                secondary_db,
                offer_id=offer_id,
                user_id=uuid4(),
            )
        assert result.state == PROMOTION_STATE_FAILED
        assert "ai_error" in result.error
        decision = secondary_db.query(Decision).filter(Decision.job_offer_id == offer_id).one()
        assert decision.promotion_state == PROMOTION_STATE_FAILED

    def test_already_done_short_circuits(self, primary_db: Any, secondary_db: Any) -> None:
        """Idempotenza: re-run su Decision già done non crea duplicati."""
        offer_id = _seed_offer(secondary_db)
        cv_id = uuid4()
        fake_cv = MagicMock(id=cv_id, raw_text="cv")

        with (
            patch("src.worldwild.services.promote.get_latest_cv", return_value=fake_cv),
            patch("src.worldwild.services.promote.check_budget_available", return_value=(True, "")),
            patch(
                "src.worldwild.services.promote.analyze_and_charge",
                side_effect=_fake_run_analysis_factory(primary_db, cv_id),
            ),
        ):
            first = send_to_pulse(
                primary_db,
                secondary_db,
                offer_id=offer_id,
                user_id=uuid4(),
            )
        assert first.state == PROMOTION_STATE_DONE
        first_analysis_id = first.analysis_id

        # Re-run: short-circuit precoce, no AI call
        with (
            patch("src.worldwild.services.promote.get_latest_cv") as mock_cv,
            patch("src.worldwild.services.promote.analyze_and_charge") as mock_run,
        ):
            second = send_to_pulse(
                primary_db,
                secondary_db,
                offer_id=offer_id,
                user_id=uuid4(),
            )
        assert second.state == PROMOTION_STATE_DONE
        assert second.skipped_reason == "already_done"
        assert second.analysis_id == first_analysis_id
        mock_cv.assert_not_called()
        mock_run.assert_not_called()
        assert primary_db.query(JobAnalysis).count() == 1

    def test_url_dedup_reuses_existing_analysis(self, primary_db: Any, secondary_db: Any) -> None:
        """Se l'URL è già stato analizzato (es. cowork paste), riusa la JobAnalysis."""
        offer_id = _seed_offer(secondary_db)
        cv_id = uuid4()
        fake_cv = MagicMock(id=cv_id, raw_text="cv")

        # Pre-populate Pulse con una JobAnalysis sullo stesso URL (cowork)
        existing = JobAnalysis(
            cv_id=cv_id,
            job_description="cowork pasted JD body",
            job_url="https://example.com/job/1",
            company="TestCorp",
            role="Senior DevOps Engineer",
            source=AnalysisSource.COWORK.value,
            score=75,
        )
        primary_db.add(existing)
        primary_db.flush()
        existing_id = existing.id

        with (
            patch("src.worldwild.services.promote.get_latest_cv", return_value=fake_cv),
            patch("src.worldwild.services.promote.check_budget_available", return_value=(True, "")),
            patch("src.worldwild.services.promote.analyze_and_charge") as mock_run,
        ):
            result = send_to_pulse(
                primary_db,
                secondary_db,
                offer_id=offer_id,
                user_id=uuid4(),
            )

        assert result.state == PROMOTION_STATE_DONE
        assert result.skipped_reason == "url_dedup"
        assert result.analysis_id == existing_id
        # Niente Claude call: la cosa importante del dedup è risparmiare credit
        mock_run.assert_not_called()
        decision = secondary_db.query(Decision).filter(Decision.job_offer_id == offer_id).one()
        assert decision.promoted_to_neon_id == existing_id
