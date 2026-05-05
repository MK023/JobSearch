"""End-to-end test of the ingest service against an in-memory SQLite DB.

Uses a dedicated SQLite engine for the secondary DB (mirrors
``database/worldwild_db.py``'s session factory) so the test never touches
Supabase. Adzuna client is monkey-patched to return canned offers.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.worldwild_db import WorldwildBase
from src.worldwild import audit_models, models  # noqa: F401  -- register tables
from src.worldwild.models import (
    DECISION_PENDING,
    RUN_STATUS_SUCCESS,
    SOURCE_ADZUNA,
    AdapterRun,
    Decision,
    JobOffer,
)
from src.worldwild.services.ingest import compute_content_hash, run_adzuna_ingest


@pytest.fixture
def worldwild_db_session() -> Any:
    """In-memory SQLite session bound to WorldwildBase.metadata."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    WorldwildBase.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


def _good_offer(idx: int = 1) -> dict[str, Any]:
    return {
        "source": "adzuna",
        "external_id": f"job-{idx}",
        "title": f"Senior DevOps Engineer #{idx}",
        "company": f"TestCorp-{idx}",
        "location": "Milano, Italia",
        "url": f"https://example.com/job/{idx}",
        "description": "Full remote, Kubernetes + AWS.",
        "salary_min": 50000,
        "salary_max": 70000,
        "salary_currency": "EUR",
        "contract_type": "permanent",
        "contract_time": "full_time",
        "category": "IT Jobs",
        "posted_at": None,
        "raw_payload": {"id": f"job-{idx}"},
    }


def _noisy_offer(idx: int = 99) -> dict[str, Any]:
    """Offer that pre-filter must reject (Help Desk title)."""
    return {
        **_good_offer(idx),
        "title": "Help Desk 1° livello",
    }


class TestComputeContentHash:
    def test_hash_is_stable_across_calls(self) -> None:
        offer = _good_offer(1)
        assert compute_content_hash(offer) == compute_content_hash(offer)

    def test_hash_differs_on_different_companies(self) -> None:
        a = _good_offer(1)
        b = {**a, "company": "AnotherCo"}
        assert compute_content_hash(a) != compute_content_hash(b)

    def test_hash_normalizes_case_and_whitespace(self) -> None:
        a = _good_offer(1)
        b = {**a, "company": " TESTCORP-1 ", "title": a["title"].upper()}
        assert compute_content_hash(a) == compute_content_hash(b)


class TestRunAdzunaIngest:
    def test_inserts_offers_with_pre_filter_outcome(self, worldwild_db_session: Any) -> None:
        # Post-feature stack-match at-ingest: gli offer che falliscono pre_filter
        # OPPURE che hanno score < threshold vengono droppati totalmente (no
        # JobOffer row) per ridurre noise nel raw layer. ``filtered_out`` riflette
        # quel drop. Il "Help Desk" qui fallisce pre_filter quindi non entra.
        offers = [_good_offer(1), _noisy_offer(2), _good_offer(3)]
        with patch("src.worldwild.services.ingest.fetch_adzuna_jobs", return_value=offers):
            result = run_adzuna_ingest(worldwild_db_session, queries=("devops",))
            worldwild_db_session.commit()

        assert result.fetched == 3
        assert result.new == 2  # solo i 2 good_offer entrano; il noisy è droppato
        assert result.filtered_out == 1

        rows = list(worldwild_db_session.execute(select(JobOffer)).scalars())
        assert len(rows) == 2
        # tutti gli inseriti hanno pre_filter_passed=True (gli scartati non entrano)
        assert all(r.pre_filter_passed for r in rows)
        assert all("DevOps" in r.title for r in rows)
        # cv_match_score popolato (>= threshold) per ogni inserito
        assert all(r.cv_match_score is not None and r.cv_match_score >= 50 for r in rows)

    def test_creates_pending_decision_for_each_offer(self, worldwild_db_session: Any) -> None:
        with patch(
            "src.worldwild.services.ingest.fetch_adzuna_jobs",
            return_value=[_good_offer(1)],
        ):
            run_adzuna_ingest(worldwild_db_session, queries=("devops",))
            worldwild_db_session.commit()

        decisions = list(worldwild_db_session.execute(select(Decision)).scalars())
        assert len(decisions) == 1
        assert decisions[0].decision == DECISION_PENDING

    def test_dedup_via_external_id_unique_constraint(self, worldwild_db_session: Any) -> None:
        # Two runs with the same offer must NOT insert a duplicate.
        offers = [_good_offer(1)]
        with patch("src.worldwild.services.ingest.fetch_adzuna_jobs", return_value=offers):
            run_adzuna_ingest(worldwild_db_session, queries=("devops",))
            worldwild_db_session.commit()

            run2 = run_adzuna_ingest(worldwild_db_session, queries=("devops",))
            worldwild_db_session.commit()

        assert run2.new == 0
        rows = list(worldwild_db_session.execute(select(JobOffer)).scalars())
        assert len(rows) == 1

    def test_run_marks_success_status_and_counters(self, worldwild_db_session: Any) -> None:
        with patch(
            "src.worldwild.services.ingest.fetch_adzuna_jobs",
            return_value=[_good_offer(1), _noisy_offer(2)],
        ):
            result = run_adzuna_ingest(worldwild_db_session, queries=("devops",))
            worldwild_db_session.commit()

        # result.run_id is the str() UUID from the service; SQLAlchemy on SQLite
        # stores UUID as bytes via the .hex codec, so we must convert back to a
        # real UUID object before the WHERE clause.
        run = worldwild_db_session.execute(select(AdapterRun).where(AdapterRun.id == UUID(result.run_id))).scalar_one()
        assert run.status == RUN_STATUS_SUCCESS
        assert run.source == SOURCE_ADZUNA
        assert run.offers_fetched == 2
        # Post-feature: noisy offer (pre_filter rejected) viene droppato → solo 1 inserito
        assert run.offers_new == 1
        assert run.offers_pre_filtered_out == 1
        assert run.completed_at is not None
        assert run.duration_ms is not None and run.duration_ms >= 0

    def test_run_records_failure_status_on_adapter_exception(self, worldwild_db_session: Any) -> None:
        def _boom(**_kw: Any) -> list[dict[str, Any]]:
            raise RuntimeError("adapter blew up")

        with patch("src.worldwild.services.ingest.fetch_adzuna_jobs", side_effect=_boom):
            with pytest.raises(RuntimeError):
                run_adzuna_ingest(worldwild_db_session, queries=("devops",))
            # On failure path, the service still flushes the failed run row.
            worldwild_db_session.commit()

        runs = list(worldwild_db_session.execute(select(AdapterRun)).scalars())
        assert len(runs) == 1
        assert runs[0].status == "failed"
        assert "adapter blew up" in runs[0].error_message
