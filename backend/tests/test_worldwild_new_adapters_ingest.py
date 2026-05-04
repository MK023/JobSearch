"""Test integration sui 8 nuovi run_<source>_ingest WorldWild.

Mocka i fetcher API specifici per source e verifica:
- AdapterRun aperto + chiuso correttamente
- JobOffer + Decision creati per ogni offerta
- pre_filter applicato (passed/failed)
- dedup cross-source (stessa content_hash da source diversa)
- IngestResult counters consistenti

Pattern fedele a ``test_worldwild_ingest_service.py`` per ``run_adzuna_ingest``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.worldwild_db import WorldwildBase
from src.worldwild import audit_models, models  # noqa: F401  -- register tables
from src.worldwild.models import (
    DECISION_PENDING,
    RUN_STATUS_SUCCESS,
    AdapterRun,
    Decision,
    JobOffer,
)


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


def _offer(source: str, idx: int = 1, *, title: str | None = None) -> dict[str, Any]:
    """Canonical normalized offer for a given source."""
    return {
        "source": source,
        "external_id": f"{source}-{idx}",
        "title": title or f"Senior DevOps Engineer #{idx}",
        "company": f"TestCorp-{source}-{idx}",
        "location": "Remote",
        "url": f"https://example.com/{source}/job/{idx}",
        "description": "Full remote, Kubernetes + AWS.",
        "salary_min": 50000,
        "salary_max": 80000,
        "salary_currency": "EUR",
        "contract_type": "full_time",
        "contract_time": "",
        "category": "IT Jobs",
        "posted_at": None,
        "raw_payload": {"id": f"{source}-{idx}"},
    }


# =============================================================================
# Test parametrizzato: ogni nuovo run_<source>_ingest deve produrre AdapterRun
# success + N JobOffer + N Decision pending quando il fetcher restituisce N offerte.
# =============================================================================


@pytest.mark.parametrize(
    ("run_func_name", "fetch_module_path", "fetch_func_name", "source_label"),
    [
        ("run_remotive_ingest", "src.worldwild.services.ingest", "fetch_remotive_jobs", "remotive"),
        ("run_arbeitnow_ingest", "src.worldwild.services.ingest", "fetch_arbeitnow_jobs", "arbeitnow"),
        ("run_jobicy_ingest", "src.worldwild.services.ingest", "fetch_jobicy_jobs", "jobicy"),
        ("run_remoteok_ingest", "src.worldwild.services.ingest", "fetch_remoteok_jobs", "remoteok"),
        ("run_themuse_ingest", "src.worldwild.services.ingest", "fetch_themuse_jobs", "themuse"),
        ("run_findwork_ingest", "src.worldwild.services.ingest", "fetch_findwork_jobs", "findwork"),
        ("run_workingnomads_ingest", "src.worldwild.services.ingest", "fetch_workingnomads_jobs", "workingnomads"),
        ("run_weworkremotely_ingest", "src.worldwild.services.ingest", "fetch_weworkremotely_jobs", "weworkremotely"),
    ],
)
def test_run_ingest_persists_offers_with_pre_filter_outcome(
    worldwild_db_session: Any,
    run_func_name: str,
    fetch_module_path: str,
    fetch_func_name: str,
    source_label: str,
) -> None:
    """Smoke test integration per ogni nuova run_<source>_ingest.

    Mocka il fetcher → 2 offerte canoniche, verifica che AdapterRun chiuda success,
    JobOffer + Decision pending vengano creati, content_hash sia popolato.
    """
    import src.worldwild.services.ingest as ingest_mod

    run_func = getattr(ingest_mod, run_func_name)
    offers = [_offer(source_label, 1), _offer(source_label, 2)]

    with patch.object(ingest_mod, fetch_func_name, return_value=offers):
        # Per i 3 source che hanno parametro `queries`, passiamo override esplicito
        if source_label in ("remotive", "themuse", "findwork"):
            result = run_func(worldwild_db_session, queries=("devops",))
        else:
            result = run_func(worldwild_db_session)
        worldwild_db_session.commit()

    # AdapterRun chiuso success
    runs = list(worldwild_db_session.execute(select(AdapterRun)).scalars())
    assert len(runs) == 1
    assert runs[0].source == source_label
    assert runs[0].status == RUN_STATUS_SUCCESS
    assert runs[0].offers_fetched == 2
    assert runs[0].offers_new == 2

    # 2 JobOffer creati con content_hash popolato + pre_filter_passed
    job_offers = list(worldwild_db_session.execute(select(JobOffer)).scalars())
    assert len(job_offers) == 2
    for jo in job_offers:
        assert jo.source == source_label
        assert jo.content_hash != ""
        assert jo.pre_filter_passed is True  # title è "Senior DevOps Engineer", whitelist match

    # 2 Decision pending sibling
    decisions = list(worldwild_db_session.execute(select(Decision)).scalars())
    assert len(decisions) == 2
    for d in decisions:
        assert d.decision == DECISION_PENDING

    # IngestResult counters
    assert result.fetched == 2
    assert result.new == 2
    assert result.filtered_out == 0


# =============================================================================
# Edge case: fetcher ritorna [] → AdapterRun chiude success con counters=0
# =============================================================================


def test_run_remotive_ingest_handles_empty_fetch(worldwild_db_session: Any) -> None:
    import src.worldwild.services.ingest as ingest_mod

    with patch.object(ingest_mod, "fetch_remotive_jobs", return_value=[]):
        result = ingest_mod.run_remotive_ingest(worldwild_db_session, queries=("devops",))
        worldwild_db_session.commit()

    runs = list(worldwild_db_session.execute(select(AdapterRun)).scalars())
    assert len(runs) == 1
    assert runs[0].status == RUN_STATUS_SUCCESS
    assert runs[0].offers_fetched == 0
    assert runs[0].offers_new == 0
    assert result.fetched == 0
    assert result.new == 0


# =============================================================================
# Edge case: pre_filter rejects (title blacklist) → JobOffer creato con
# pre_filter_passed=False, ma comunque persistito (observability-first design)
# =============================================================================


def test_run_jobicy_ingest_records_pre_filter_failure(worldwild_db_session: Any) -> None:
    import src.worldwild.services.ingest as ingest_mod

    bad_offer = _offer("jobicy", 1, title="Help Desk Junior livello 1")  # blacklist
    with patch.object(ingest_mod, "fetch_jobicy_jobs", return_value=[bad_offer]):
        result = ingest_mod.run_jobicy_ingest(worldwild_db_session)
        worldwild_db_session.commit()

    job_offers = list(worldwild_db_session.execute(select(JobOffer)).scalars())
    assert len(job_offers) == 1
    assert job_offers[0].pre_filter_passed is False
    assert job_offers[0].pre_filter_reason  # reason populated

    # Counters: fetched=1, new=1 (riga creata comunque), filtered_out=1
    assert result.fetched == 1
    assert result.new == 1
    assert result.filtered_out == 1


# =============================================================================
# Edge case: cross-source dedup — stesso content_hash da fonti diverse =
# secondo insert skippato silenziosamente
# =============================================================================


def test_run_arbeitnow_skips_offer_already_present_via_content_hash(
    worldwild_db_session: Any,
) -> None:
    import src.worldwild.services.ingest as ingest_mod

    # Pre-popola DB con un'offerta da Adzuna
    seed = _offer("adzuna", 1)
    seed_hash = ingest_mod.compute_content_hash(seed)
    worldwild_db_session.add(
        JobOffer(
            source="adzuna",
            external_id="adzuna-1",
            content_hash=seed_hash,
            title=seed["title"],
            company=seed["company"],
            location=seed["location"],
            url=seed["url"],
            description=seed["description"],
            salary_min=seed["salary_min"],
            salary_max=seed["salary_max"],
            salary_currency=seed["salary_currency"],
            contract_type=seed["contract_type"],
            contract_time=seed["contract_time"],
            category=seed["category"],
            posted_at=seed["posted_at"],
            pre_filter_passed=True,
            pre_filter_reason="",
            raw_payload=seed["raw_payload"],
        )
    )
    worldwild_db_session.commit()

    # Stessa offerta arriva da Arbeitnow → stesso content_hash
    same_offer_via_arbeitnow = {**seed, "source": "arbeitnow", "external_id": "arbeitnow-1"}
    with patch.object(ingest_mod, "fetch_arbeitnow_jobs", return_value=[same_offer_via_arbeitnow]):
        result = ingest_mod.run_arbeitnow_ingest(worldwild_db_session)
        worldwild_db_session.commit()

    # Solo 1 JobOffer ancora in DB (il seed Adzuna), no nuovi insert
    job_offers = list(worldwild_db_session.execute(select(JobOffer)).scalars())
    assert len(job_offers) == 1
    assert job_offers[0].source == "adzuna"
    assert result.fetched == 1
    assert result.new == 0


# =============================================================================
# Edge case: fetcher solleva → AdapterRun chiuso failed + exception propagata
# =============================================================================


def test_run_themuse_ingest_marks_run_failed_on_fetcher_exception(
    worldwild_db_session: Any,
) -> None:
    import src.worldwild.services.ingest as ingest_mod
    from src.worldwild.models import RUN_STATUS_FAILED

    def _boom(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        raise RuntimeError("themuse 503 simulated")

    with patch.object(ingest_mod, "fetch_themuse_jobs", side_effect=_boom):
        with pytest.raises(RuntimeError, match="themuse 503 simulated"):
            ingest_mod.run_themuse_ingest(worldwild_db_session, queries=("Engineering",))
        worldwild_db_session.commit()

    runs = list(worldwild_db_session.execute(select(AdapterRun)).scalars())
    assert len(runs) == 1
    assert runs[0].status == RUN_STATUS_FAILED
    assert "themuse 503 simulated" in (runs[0].error_message or "")


# =============================================================================
# Default queries dal YAML — verify _default_queries integration
# =============================================================================


def test_run_remotive_ingest_uses_yaml_default_queries_when_none(
    worldwild_db_session: Any,
) -> None:
    """Quando ``queries=None``, run_remotive_ingest carica da config/queries.yaml."""
    import src.worldwild.services.ingest as ingest_mod

    captured_queries: list[str] = []

    def _capture(query: str = "", **_kwargs: Any) -> list[dict[str, Any]]:
        captured_queries.append(query)
        return []

    with patch.object(ingest_mod, "fetch_remotive_jobs", side_effect=_capture):
        ingest_mod.run_remotive_ingest(worldwild_db_session)
        worldwild_db_session.commit()

    # Il YAML ha 4 default queries per remotive (devops, sre, cloud, python)
    assert len(captured_queries) == 4
    assert "devops" in captured_queries
