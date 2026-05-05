"""WorldWild ingest orchestration: fetch → dedup → pre-filter → persist.

Una funzione ``run_<source>_ingest`` per ogni adapter (no factory generica per
scelta di Marco). Tutte condividono helper privati che evitano duplicazione
del pattern dedup/pre_filter/AdapterRun.

Flow per ogni source:

1. Open ``AdapterRun`` row with ``status='running'``.
2. Fetch via client API specifico (``integrations/<source>.py``).
3. Per ogni offer normalizzato:
   a. compute ``content_hash`` (cross-source dedup key).
   b. skip se JobOffer con quel hash già esiste.
   c. applica ``pre_filter`` rules.
   d. insert ``JobOffer`` (con ``pre_filter_passed`` + ``pre_filter_reason``).
   e. insert sibling ``Decision`` con ``decision='pending'``.
4. Close ``AdapterRun`` con counters e ``status='success'`` / ``'failed'``.

Il pre-filter outcome è registrato sulla row, NON droppa l'insert — observability
("quanti filtrati oggi e perché"), più la possibilità di allentare regole dopo
senza perdere dati.
"""

import hashlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import settings
from ...integrations.adzuna import fetch_adzuna_jobs
from ...integrations.arbeitnow import fetch_arbeitnow_jobs
from ...integrations.findwork import fetch_findwork_jobs
from ...integrations.jobicy import fetch_jobicy_jobs
from ...integrations.remoteok import fetch_remoteok_jobs
from ...integrations.remotive import fetch_remotive_jobs
from ...integrations.themuse import fetch_themuse_jobs
from ...integrations.weworkremotely import fetch_weworkremotely_jobs
from ...integrations.workingnomads import fetch_workingnomads_jobs
from ..config import load_queries_config
from ..filters import pre_filter
from ..models import (
    DECISION_PENDING,
    RUN_STATUS_FAILED,
    RUN_STATUS_RUNNING,
    RUN_STATUS_SUCCESS,
    SOURCE_ADZUNA,
    SOURCE_ARBEITNOW,
    SOURCE_FINDWORK,
    SOURCE_JOBICY,
    SOURCE_REMOTEOK,
    SOURCE_REMOTIVE,
    SOURCE_THEMUSE,
    SOURCE_WEWORKREMOTELY,
    SOURCE_WORKINGNOMADS,
    AdapterRun,
    Decision,
    JobOffer,
)
from ..stack_extract import extract_stack
from ..stack_match import score_match


def _default_queries(source_key: str) -> tuple[str, ...]:
    """Resolve default queries per source da ``config/queries.yaml`` (cached upstream).

    Marco edita il YAML per cambiare cosa cercare, niente code push. Fallback a
    tuple vuota se mancano: ingest semplicemente non lancia query (fail-safe).
    """
    cfg = load_queries_config().get(source_key, {})
    queries = cfg.get("default_queries") or []
    return tuple(queries)


def _default_adzuna_queries() -> tuple[str, ...]:
    """Backward-compat alias usato dai test esistenti."""
    return _default_queries("adzuna")


class IngestResult:
    """Plain container for what the route / cron handler reports back."""

    def __init__(self, run_id: str, fetched: int, new: int, filtered_out: int) -> None:
        self.run_id = run_id
        self.fetched = fetched
        self.new = new
        self.filtered_out = filtered_out


def compute_content_hash(offer: dict[str, Any]) -> str:
    """Stable dedup key across sources.

    Build the hash from ``company + title + location + ISO week of posted_at``
    (or ingestion week if ``posted_at`` missing). Hashing on an ISO week (not
    the exact timestamp) means the same posting picked up by two different
    sources within the same week collapses to one row, even if the seconds
    differ. SHA-256 truncated to 64 hex chars matches the column width.
    """
    company = (offer.get("company") or "").strip().lower()
    title = (offer.get("title") or "").strip().lower()
    location = (offer.get("location") or "").strip().lower()
    when = offer.get("posted_at") or datetime.now(UTC)
    if not isinstance(when, datetime):
        when = datetime.now(UTC)
    iso_year, iso_week, _ = when.isocalendar()
    payload = f"{company}|{title}|{location}|{iso_year}-W{iso_week:02d}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_adzuna_ingest(
    db: Session,
    *,
    queries: tuple[str, ...] | None = None,
    run_type: str = "manual",
) -> IngestResult:
    """Execute one ingest run against Adzuna IT.

    Caller owns the transaction: we ``flush`` so newly-inserted rows are visible
    for dedup within the same run, but we do NOT ``commit`` — that's the
    caller's call (route / cron). On exception we re-raise after marking the
    run as failed so retries / Sentry get the full picture.

    Args:
        queries: tuple di query Adzuna. ``None`` (default) = leggi da
            ``config/queries.yaml`` chiave ``adzuna.default_queries``.
            Pass esplicito per override (es. test, query ad-hoc).
    """
    if queries is None:
        queries = _default_adzuna_queries()

    def _fetch() -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for query in queries or ():
            results.extend(fetch_adzuna_jobs(what=query))
        return results

    return _execute_ingest(db, SOURCE_ADZUNA, fetch_offers=_fetch, run_type=run_type)


def _compute_cv_match_score(offer: dict[str, Any]) -> int | None:
    """Stack-match at-ingest contro ``MARCO_CV_SKILLS`` (deterministico, no AI).

    Riusa ``extract_stack`` + ``score_match`` (vedi ``services/promote.py`` per
    lo stesso pattern in fase di promozione). Ritorna ``None`` quando l'offer
    non ha tech tokens estraibili: in quel caso lo score non è semanticamente
    "0" (il match è indeterminabile, non basso) e lasciamo la decisione di
    inserimento al solo pre_filter (la threshold non si applica).
    """
    extracted = extract_stack(offer)
    if not extracted:
        return None
    return score_match(extracted).score


def _below_match_threshold(cv_match_score: int | None) -> bool:
    """True quando la score esiste ed è sotto ``settings.promote_score_threshold``.

    ``None`` (offer non scoreable) NON è considerato sotto-threshold: in quel
    caso non blocchiamo l'insert, l'offer passa avanti col solo verdetto del
    pre_filter (default safety, evita di perdere segnali quando il vocabolario
    di stack-extract non copre il dominio dell'offer).
    """
    if cv_match_score is None:
        return False
    return cv_match_score < settings.promote_score_threshold


def _exists(db: Session, *, content_hash: str, source: str, external_id: str) -> bool:
    """True if we already have this offer (cross-source via hash, intra-source via external_id)."""
    stmt = (
        select(JobOffer.id)
        .where(
            (JobOffer.content_hash == content_hash)
            | ((JobOffer.source == source) & (JobOffer.external_id == external_id))
        )
        .limit(1)
    )
    return db.execute(stmt).first() is not None


# =============================================================================
# Helper comune per i nuovi adapter (Remotive, Arbeitnow, Jobicy, RemoteOK,
# TheMuse, Findwork, WorkingNomads, WeWorkRemotely).
#
# Adzuna mantiene la sua run_adzuna_ingest dedicata sopra per compatibilità
# coi test esistenti — il pattern interno è equivalente.
# =============================================================================

from collections.abc import Callable  # noqa: E402  (kept near helpers, post-class)


def _execute_ingest(
    db: Session,
    source: str,
    *,
    fetch_offers: Callable[[], list[dict[str, Any]]],
    run_type: str = "manual",
) -> IngestResult:
    """Orchestrazione condivisa: apre AdapterRun, esegue fetch, dedup+pre_filter+persist, chiude run.

    ``fetch_offers``: closure che ritorna la lista già normalizzata di offers
    per quella source (parametri specifici al fetcher li chiude la closure).
    """
    run = AdapterRun(
        source=source,
        run_type=run_type,
        status=RUN_STATUS_RUNNING,
    )
    db.add(run)
    db.flush()
    started = datetime.now(UTC)

    fetched = 0
    new_count = 0
    filtered_out = 0

    try:
        offers = fetch_offers()
        fetched = len(offers)
        for offer in offers:
            content_hash = compute_content_hash(offer)
            if _exists(
                db,
                content_hash=content_hash,
                source=offer["source"],
                external_id=offer["external_id"],
            ):
                continue
            passed, reason = pre_filter(offer)
            # Stack-match score at-ingest contro Marco's CV (deterministico,
            # no AI cost). Se la score è sotto threshold OPPURE pre_filter
            # è fallito, NON inseriamo la riga: drop totale per ridurre
            # noise nel raw layer (osservabilità ridotta a contatore +
            # row su AdapterRun, dettaglio in Sentry per debugging).
            cv_match_score = _compute_cv_match_score(offer)
            if not passed or _below_match_threshold(cv_match_score):
                filtered_out += 1
                continue
            job_offer = JobOffer(
                source=offer["source"],
                external_id=offer["external_id"],
                content_hash=content_hash,
                title=offer["title"],
                company=offer.get("company", ""),
                location=offer.get("location", ""),
                url=offer.get("url", ""),
                description=offer.get("description", ""),
                salary_min=offer.get("salary_min"),
                salary_max=offer.get("salary_max"),
                salary_currency=offer.get("salary_currency", ""),
                contract_type=offer.get("contract_type", ""),
                contract_time=offer.get("contract_time", ""),
                category=offer.get("category", ""),
                posted_at=offer.get("posted_at"),
                pre_filter_passed=passed,
                pre_filter_reason=reason,
                cv_match_score=cv_match_score,
                raw_payload=offer.get("raw_payload"),
            )
            db.add(job_offer)
            db.flush()
            db.add(Decision(job_offer_id=job_offer.id, decision=DECISION_PENDING))
            new_count += 1
        run.status = RUN_STATUS_SUCCESS  # type: ignore[assignment]
    except Exception as exc:
        run.status = RUN_STATUS_FAILED  # type: ignore[assignment]
        run.error_message = f"{type(exc).__name__}: {exc}"[:4000]  # type: ignore[assignment]
        run.completed_at = datetime.now(UTC)  # type: ignore[assignment]
        run.duration_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)  # type: ignore[assignment]
        run.offers_fetched = fetched  # type: ignore[assignment]
        run.offers_new = new_count  # type: ignore[assignment]
        run.offers_pre_filtered_out = filtered_out  # type: ignore[assignment]
        db.flush()
        raise
    finally:
        if run.status != RUN_STATUS_FAILED:
            run.completed_at = datetime.now(UTC)  # type: ignore[assignment]
            run.duration_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)  # type: ignore[assignment]
            run.offers_fetched = fetched  # type: ignore[assignment]
            run.offers_new = new_count  # type: ignore[assignment]
            run.offers_pre_filtered_out = filtered_out  # type: ignore[assignment]
            db.flush()

    return IngestResult(
        run_id=str(run.id),
        fetched=fetched,
        new=new_count,
        filtered_out=filtered_out,
    )


# =============================================================================
# 8 nuove funzioni run_<source>_ingest — una per adapter.
# Ognuna chiude i parametri specifici sul fetcher e delega a _execute_ingest.
# =============================================================================


def run_remotive_ingest(
    db: Session,
    *,
    queries: tuple[str, ...] | None = None,
    run_type: str = "manual",
) -> IngestResult:
    """Ingest run su Remotive (search-based, no auth). Una call per query."""
    if queries is None:
        queries = _default_queries("remotive")

    def _fetch() -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for q in queries or ():
            results.extend(fetch_remotive_jobs(query=q))
        return results

    return _execute_ingest(db, SOURCE_REMOTIVE, fetch_offers=_fetch, run_type=run_type)


def run_arbeitnow_ingest(
    db: Session,
    *,
    max_pages: int = 5,
    remote_only: bool = True,
    run_type: str = "manual",
) -> IngestResult:
    """Ingest run su Arbeitnow (page-based, no query, filtro remote-only client-side)."""

    def _fetch() -> list[dict[str, Any]]:
        return fetch_arbeitnow_jobs(max_pages=max_pages, remote_only=remote_only)

    return _execute_ingest(db, SOURCE_ARBEITNOW, fetch_offers=_fetch, run_type=run_type)


def run_jobicy_ingest(
    db: Session,
    *,
    industry: str = "",
    geo: str = "",
    tag: str = "",
    count: int = 50,
    run_type: str = "manual",
) -> IngestResult:
    """Ingest run su Jobicy (single fetch con filtri industry/geo/tag opzionali)."""

    def _fetch() -> list[dict[str, Any]]:
        return fetch_jobicy_jobs(industry=industry, geo=geo, tag=tag, count=count)

    return _execute_ingest(db, SOURCE_JOBICY, fetch_offers=_fetch, run_type=run_type)


def run_remoteok_ingest(
    db: Session,
    *,
    tags: tuple[str, ...] = (),
    run_type: str = "manual",
) -> IngestResult:
    """Ingest run su Remote OK (single fetch con tags filter, User-Agent custom)."""

    def _fetch() -> list[dict[str, Any]]:
        return fetch_remoteok_jobs(tags=tags)

    return _execute_ingest(db, SOURCE_REMOTEOK, fetch_offers=_fetch, run_type=run_type)


def run_themuse_ingest(
    db: Session,
    *,
    queries: tuple[str, ...] | None = None,
    location: str = "",
    max_pages: int = 5,
    api_key: str = "",
    run_type: str = "manual",
) -> IngestResult:
    """Ingest run su The Muse (page-based, queries usate come ``category``)."""
    if queries is None:
        queries = _default_queries("themuse")

    def _fetch() -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for category in queries or ():
            results.extend(
                fetch_themuse_jobs(
                    category=category,
                    location=location,
                    max_pages=max_pages,
                    api_key=api_key,
                )
            )
        return results

    return _execute_ingest(db, SOURCE_THEMUSE, fetch_offers=_fetch, run_type=run_type)


def run_findwork_ingest(
    db: Session,
    *,
    queries: tuple[str, ...] | None = None,
    location: str = "",
    remote: bool | None = True,
    max_pages: int = 5,
    run_type: str = "manual",
) -> IngestResult:
    """Ingest run su Findwork (auth via FINDWORK_API_KEY, search-based)."""
    if queries is None:
        queries = _default_queries("findwork")

    def _fetch() -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for q in queries or ():
            results.extend(
                fetch_findwork_jobs(
                    search=q,
                    location=location,
                    remote=remote,
                    max_pages=max_pages,
                )
            )
        return results

    return _execute_ingest(db, SOURCE_FINDWORK, fetch_offers=_fetch, run_type=run_type)


def run_workingnomads_ingest(
    db: Session,
    *,
    category_filter: str = "",
    run_type: str = "manual",
) -> IngestResult:
    """Ingest run su Working Nomads (single fetch, filtro category client-side)."""

    def _fetch() -> list[dict[str, Any]]:
        return fetch_workingnomads_jobs(category_filter=category_filter)

    return _execute_ingest(db, SOURCE_WORKINGNOMADS, fetch_offers=_fetch, run_type=run_type)


def run_weworkremotely_ingest(
    db: Session,
    *,
    category: str = "remote-devops-sysadmin-jobs",
    run_type: str = "manual",
) -> IngestResult:
    """Ingest run su We Work Remotely (RSS feed per category)."""

    def _fetch() -> list[dict[str, Any]]:
        return fetch_weworkremotely_jobs(category=category)

    return _execute_ingest(db, SOURCE_WEWORKREMOTELY, fetch_offers=_fetch, run_type=run_type)
