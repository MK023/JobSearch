"""Adzuna ingest orchestration: fetch → dedup → pre-filter → persist.

The flow:

1. Open ``AdapterRun`` row with ``status='running'``.
2. For each query in ``queries``, call the Adzuna client.
3. For each returned offer:
   a. compute ``content_hash`` (stable cross-source dedup key).
   b. skip if a JobOffer with that hash already exists (intra- or cross-source).
   c. apply ``pre_filter`` rules.
   d. insert ``JobOffer`` row (with ``pre_filter_passed`` and ``pre_filter_reason``).
   e. insert sibling ``Decision`` row with ``decision='pending'``.
4. Close ``AdapterRun`` with counters and ``status='success'`` / ``'failed'``.

The pre-filter outcome is recorded on the row, NOT used to drop the insert —
this gives us observability ("how many were filtered out today, and why"),
plus the option to loosen rules later without losing data.
"""

import hashlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...integrations.adzuna import fetch_adzuna_jobs
from ..filters import pre_filter
from ..models import (
    DECISION_PENDING,
    RUN_STATUS_FAILED,
    RUN_STATUS_RUNNING,
    RUN_STATUS_SUCCESS,
    SOURCE_ADZUNA,
    AdapterRun,
    Decision,
    JobOffer,
)

# Default queries for the Italian Adzuna market. Picks both buckets that
# Marco's funnel actually converts on (Dev 14.3% / Cloud 3.8% per career-kit
# `linkedin_572_deep_dive.md`). We hit the API once per query — Adzuna's free
# tier gives 1k calls/day, so 4 queries × 4 pages = 16 calls per cron run is
# orders of magnitude under the cap.
DEFAULT_ADZUNA_QUERIES = (
    "devops",
    "site reliability engineer",
    "cloud engineer",
    "python developer",
)


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
    queries: tuple[str, ...] = DEFAULT_ADZUNA_QUERIES,
    run_type: str = "manual",
) -> IngestResult:
    """Execute one ingest run against Adzuna IT.

    Caller owns the transaction: we ``flush`` so newly-inserted rows are visible
    for dedup within the same run, but we do NOT ``commit`` — that's the
    caller's call (route / cron). On exception we re-raise after marking the
    run as failed so retries / Sentry get the full picture.
    """
    run = AdapterRun(
        source=SOURCE_ADZUNA,
        run_type=run_type,
        status=RUN_STATUS_RUNNING,
    )
    db.add(run)
    db.flush()  # populate run.id
    started = datetime.now(UTC)

    fetched = 0
    new_count = 0
    filtered_out = 0

    try:
        for query in queries:
            results = fetch_adzuna_jobs(what=query)
            fetched += len(results)
            for offer in results:
                content_hash = compute_content_hash(offer)
                if _exists(db, content_hash=content_hash, source=offer["source"], external_id=offer["external_id"]):
                    continue
                passed, reason = pre_filter(offer)
                if not passed:
                    filtered_out += 1
                job_offer = JobOffer(
                    source=offer["source"],
                    external_id=offer["external_id"],
                    content_hash=content_hash,
                    title=offer["title"],
                    company=offer["company"],
                    location=offer["location"],
                    url=offer["url"],
                    description=offer["description"],
                    salary_min=offer["salary_min"],
                    salary_max=offer["salary_max"],
                    salary_currency=offer["salary_currency"],
                    contract_type=offer["contract_type"],
                    contract_time=offer["contract_time"],
                    category=offer["category"],
                    posted_at=offer["posted_at"],
                    pre_filter_passed=passed,
                    pre_filter_reason=reason,
                    raw_payload=offer["raw_payload"],
                )
                db.add(job_offer)
                db.flush()  # populate job_offer.id for the Decision FK-by-value
                db.add(Decision(job_offer_id=job_offer.id, decision=DECISION_PENDING))
                new_count += 1
        # SQLAlchemy mypy plugin reports Column[X] for descriptors here even
        # though runtime assignment to an instance attribute correctly receives
        # the bare value type. Same pattern is used across the codebase
        # (see ``inbox/service.py``, ``batch/service.py``).
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
