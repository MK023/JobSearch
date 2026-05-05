"""Cross-source decision conflict: dedup garantisce che una decisione presa
su una sorgente persiste implicitamente quando la stessa offerta arriva da
altre sorgenti.

Pattern: dedup via ``content_hash`` (company|title|location|iso_week) blocca
INSERT cross-source dentro ``_execute_ingest`` / ``run_adzuna_ingest`` tramite
``_exists()``. Conseguenza:

- nessuna nuova ``JobOffer`` row viene inserita (skip silenzioso),
- nessuna nuova ``Decision`` sibling viene creata,
- la ``Decision`` originale (``skip`` / ``promote`` / ``pending``) di Marco
  resta come single source of truth implicita.

Questi test documentano il comportamento end-to-end (esiste già un test in
``test_worldwild_new_adapters_ingest.py`` che copre il flow "fresh ingest da
seed", qui copriamo il flow "decisione già presa preservata").
"""

from __future__ import annotations

from datetime import UTC, datetime
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
    DECISION_PROMOTE,
    DECISION_SKIP,
    Decision,
    JobOffer,
)
from src.worldwild.services.ingest import compute_content_hash


@pytest.fixture
def worldwild_db_session() -> Any:
    """In-memory SQLite session bound a ``WorldwildBase.metadata``."""
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


def _offer(source: str, idx: int = 1, *, title: str | None = None, company: str | None = None) -> dict[str, Any]:
    """Offerta normalizzata canonica per una source data.

    Copia dal pattern di ``test_worldwild_new_adapters_ingest._offer`` con
    override opzionali di ``title`` e ``company`` per pilotare l'hash.
    """
    return {
        "source": source,
        "external_id": f"{source}-{idx}",
        "title": title or f"Senior DevOps Engineer #{idx}",
        "company": company or f"TestCorp-shared-{idx}",
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


def _seed_offer_with_decision(
    db: Any,
    *,
    source: str,
    idx: int,
    decision_value: str,
    title: str | None = None,
    company: str | None = None,
    posted_at: datetime | None = None,
) -> tuple[JobOffer, Decision]:
    """Helper: pre-popola DB con ``JobOffer`` + ``Decision`` collegata.

    Simula lo stato "Marco ha già visto e deciso" prima del nuovo ingest da
    altra sorgente. ``content_hash`` ricalcolato dallo stesso ``compute_content_hash``
    usato dal service (single source of truth, no re-implementazione).
    """
    payload = _offer(source, idx, title=title, company=company)
    if posted_at is not None:
        payload["posted_at"] = posted_at
    content_hash = compute_content_hash(payload)
    job = JobOffer(
        source=source,
        external_id=payload["external_id"],
        content_hash=content_hash,
        title=payload["title"],
        company=payload["company"],
        location=payload["location"],
        url=payload["url"],
        description=payload["description"],
        salary_min=payload["salary_min"],
        salary_max=payload["salary_max"],
        salary_currency=payload["salary_currency"],
        contract_type=payload["contract_type"],
        contract_time=payload["contract_time"],
        category=payload["category"],
        posted_at=payload["posted_at"],
        pre_filter_passed=True,
        pre_filter_reason="",
        raw_payload=payload["raw_payload"],
    )
    db.add(job)
    db.flush()
    decision = Decision(job_offer_id=job.id, decision=decision_value)
    db.add(decision)
    db.commit()
    return job, decision


# =============================================================================
# Test 1: skip su Adzuna → ingest stesso content_hash da Remotive →
# nessuna nuova Decision, nessuna nuova JobOffer, decisione `skip` preservata.
# =============================================================================


def test_skip_decision_preserved_when_same_offer_arrives_from_remotive(
    worldwild_db_session: Any,
) -> None:
    import src.worldwild.services.ingest as ingest_mod

    # Marco ha già skippato l'offerta ingerita da Adzuna.
    seed_job, seed_decision = _seed_offer_with_decision(
        worldwild_db_session,
        source="adzuna",
        idx=1,
        decision_value=DECISION_SKIP,
    )
    seed_decision_id = seed_decision.id

    # Stessa offerta (stesso content_hash) appare ora su Remotive.
    same_offer_via_remotive = _offer("remotive", idx=1)
    # Allineo i campi che concorrono al content_hash (company/title/location/posted_at).
    same_offer_via_remotive["company"] = seed_job.company
    same_offer_via_remotive["title"] = seed_job.title
    same_offer_via_remotive["location"] = seed_job.location

    with patch.object(ingest_mod, "fetch_remotive_jobs", return_value=[same_offer_via_remotive]):
        result = ingest_mod.run_remotive_ingest(worldwild_db_session, queries=("devops",))
        worldwild_db_session.commit()

    # Counters: fetched=1 ma new=0 (dedup hit).
    assert result.fetched == 1
    assert result.new == 0

    # Solo 1 JobOffer in DB, ancora la seed Adzuna.
    job_offers = list(worldwild_db_session.execute(select(JobOffer)).scalars())
    assert len(job_offers) == 1
    assert job_offers[0].source == "adzuna"

    # Solo 1 Decision in DB: la skip originale, intatta.
    decisions = list(worldwild_db_session.execute(select(Decision)).scalars())
    assert len(decisions) == 1
    assert decisions[0].id == seed_decision_id
    assert decisions[0].decision == DECISION_SKIP


# =============================================================================
# Test 2: promote su Adzuna → ingest stessa offerta da Arbeitnow →
# decisione `promote` preservata, nessuna riga duplicata.
# =============================================================================


def test_promote_decision_preserved_when_same_offer_arrives_from_arbeitnow(
    worldwild_db_session: Any,
) -> None:
    import src.worldwild.services.ingest as ingest_mod

    seed_job, seed_decision = _seed_offer_with_decision(
        worldwild_db_session,
        source="adzuna",
        idx=2,
        decision_value=DECISION_PROMOTE,
    )
    seed_decision_id = seed_decision.id

    same_offer_via_arbeitnow = _offer("arbeitnow", idx=2)
    same_offer_via_arbeitnow["company"] = seed_job.company
    same_offer_via_arbeitnow["title"] = seed_job.title
    same_offer_via_arbeitnow["location"] = seed_job.location

    with patch.object(ingest_mod, "fetch_arbeitnow_jobs", return_value=[same_offer_via_arbeitnow]):
        result = ingest_mod.run_arbeitnow_ingest(worldwild_db_session)
        worldwild_db_session.commit()

    assert result.fetched == 1
    assert result.new == 0

    job_offers = list(worldwild_db_session.execute(select(JobOffer)).scalars())
    assert len(job_offers) == 1
    assert job_offers[0].source == "adzuna"

    decisions = list(worldwild_db_session.execute(select(Decision)).scalars())
    assert len(decisions) == 1
    assert decisions[0].id == seed_decision_id
    assert decisions[0].decision == DECISION_PROMOTE


# =============================================================================
# Test 3: pending su Adzuna (Marco non ha ancora deciso) → ingest stessa
# offerta da Jobicy → la Decision pending originale resta single source of truth.
# =============================================================================


def test_pending_decision_preserved_when_same_offer_arrives_from_jobicy(
    worldwild_db_session: Any,
) -> None:
    import src.worldwild.services.ingest as ingest_mod

    seed_job, seed_decision = _seed_offer_with_decision(
        worldwild_db_session,
        source="adzuna",
        idx=3,
        decision_value=DECISION_PENDING,
    )
    seed_decision_id = seed_decision.id

    same_offer_via_jobicy = _offer("jobicy", idx=3)
    same_offer_via_jobicy["company"] = seed_job.company
    same_offer_via_jobicy["title"] = seed_job.title
    same_offer_via_jobicy["location"] = seed_job.location

    with patch.object(ingest_mod, "fetch_jobicy_jobs", return_value=[same_offer_via_jobicy]):
        result = ingest_mod.run_jobicy_ingest(worldwild_db_session)
        worldwild_db_session.commit()

    assert result.fetched == 1
    assert result.new == 0

    job_offers = list(worldwild_db_session.execute(select(JobOffer)).scalars())
    assert len(job_offers) == 1

    decisions = list(worldwild_db_session.execute(select(Decision)).scalars())
    assert len(decisions) == 1
    assert decisions[0].id == seed_decision_id
    assert decisions[0].decision == DECISION_PENDING


# =============================================================================
# Test 4: due offerte con content_hash DIVERSI (company diverso) tra Adzuna e
# Remotive → entrambe inserite, 2 Decision sibling separate.
# Negative-control del meccanismo di dedup.
# =============================================================================


def test_different_companies_produce_separate_rows_and_decisions(
    worldwild_db_session: Any,
) -> None:
    import src.worldwild.services.ingest as ingest_mod

    # Seed: offerta Adzuna con company "AcmeCorp", Marco l'ha skippata.
    _seed_offer_with_decision(
        worldwild_db_session,
        source="adzuna",
        idx=4,
        decision_value=DECISION_SKIP,
        company="AcmeCorp",
    )

    # Offerta diversa: stesso titolo ma company "BetaCorp" → content_hash diverso.
    other_company_offer = _offer("remotive", idx=4, company="BetaCorp")

    with patch.object(ingest_mod, "fetch_remotive_jobs", return_value=[other_company_offer]):
        result = ingest_mod.run_remotive_ingest(worldwild_db_session, queries=("devops",))
        worldwild_db_session.commit()

    # Counters: fetched=1 e new=1 (no dedup hit, due offerte diverse).
    assert result.fetched == 1
    assert result.new == 1

    # 2 JobOffer in DB: il seed Adzuna + la nuova Remotive.
    job_offers = list(worldwild_db_session.execute(select(JobOffer)).scalars())
    assert len(job_offers) == 2
    sources = {jo.source for jo in job_offers}
    assert sources == {"adzuna", "remotive"}

    # 2 Decision sibling: la skip originale + la pending fresca per la nuova offerta.
    decisions = list(worldwild_db_session.execute(select(Decision)).scalars())
    assert len(decisions) == 2
    decision_values = {d.decision for d in decisions}
    assert decision_values == {DECISION_SKIP, DECISION_PENDING}


# =============================================================================
# Test 5: stessa offerta ma settimana ISO diversa → 2 row distinte.
# Documenta il comportamento "fresh ingest next week": il content_hash include
# l'iso_week, quindi la stessa posting ricomparsa la settimana dopo è trattata
# come nuova (Marco la rivede + ridecide).
# =============================================================================


def test_same_offer_in_different_iso_week_produces_separate_rows(
    worldwild_db_session: Any,
) -> None:
    import src.worldwild.services.ingest as ingest_mod

    # Seed Adzuna con posted_at in settimana ISO 2026-W10 (Marco l'ha skippata).
    week_10 = datetime(2026, 3, 5, 12, 0, tzinfo=UTC)  # giovedì W10
    _seed_offer_with_decision(
        worldwild_db_session,
        source="adzuna",
        idx=5,
        decision_value=DECISION_SKIP,
        posted_at=week_10,
    )

    # Stessa company/title/location ma posted_at in W12 → hash diverso.
    week_12 = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)  # giovedì W12
    next_week_offer = _offer("remotive", idx=5)
    next_week_offer["company"] = "TestCorp-shared-5"
    next_week_offer["posted_at"] = week_12

    with patch.object(ingest_mod, "fetch_remotive_jobs", return_value=[next_week_offer]):
        result = ingest_mod.run_remotive_ingest(worldwild_db_session, queries=("devops",))
        worldwild_db_session.commit()

    assert result.fetched == 1
    assert result.new == 1

    # 2 JobOffer distinte (settimane ISO diverse → hash diversi).
    job_offers = list(worldwild_db_session.execute(select(JobOffer).order_by(JobOffer.source)).scalars())
    assert len(job_offers) == 2
    hashes = {jo.content_hash for jo in job_offers}
    assert len(hashes) == 2  # i due hash sono effettivamente diversi

    # 2 Decision: skip (settimana 10) + pending fresca (settimana 12).
    decisions = list(worldwild_db_session.execute(select(Decision)).scalars())
    assert len(decisions) == 2
    decision_values = {d.decision for d in decisions}
    assert decision_values == {DECISION_SKIP, DECISION_PENDING}
