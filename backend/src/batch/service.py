"""Batch analysis service.

Manages a persistent queue of job descriptions to analyze sequentially.
State is stored in PostgreSQL via the BatchItem model.
"""

import logging
import time
import uuid as uuid_mod
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..analysis.service import find_existing_analysis, run_analysis
from ..cv.service import get_latest_cv
from ..dashboard.service import add_spending
from ..integrations.anthropic_client import MODELS, content_hash
from ..integrations.cache import CacheService
from .models import BatchItem, BatchItemStatus

logger = logging.getLogger(__name__)

# Max seconds to wait for a single Haiku analysis.
# Haiku typically responds in 3-5s. If it takes longer than 45s
# on free tier, it's stalled — skip and move on.
_BATCH_ITEM_TIMEOUT = 45


def add_to_queue(
    db: Session,
    cv_id: UUID,
    job_description: str,
    job_url: str = "",
    model: str = "haiku",
    cv_text: str = "",
) -> tuple[str, int, int]:
    """Add a job to the pending batch queue.

    Before inserting, checks for existing analysis (dedup).
    Returns (batch_id, total_count, skipped_count).
    """
    # Find or create a pending batch
    existing_batch = (
        db.query(BatchItem.batch_id)
        .filter(BatchItem.status == BatchItemStatus.PENDING)
        .group_by(BatchItem.batch_id)
        .first()
    )
    batch_id = existing_batch[0] if existing_batch else str(uuid_mod.uuid4())

    # Compute content hash for dedup
    ch = content_hash(cv_text, job_description)
    model_id = MODELS.get(model, MODELS["haiku"])

    # Check if analysis already exists
    existing = find_existing_analysis(db, ch, model_id)

    preview = job_description[:80] + "..." if len(job_description) > 80 else job_description

    item = BatchItem(
        batch_id=batch_id,
        cv_id=cv_id,
        job_description=job_description,
        job_url=job_url,
        content_hash=ch,
        model=model,
        preview=preview,
    )

    if existing:
        item.status = BatchItemStatus.SKIPPED  # type: ignore[assignment]
        item.analysis_id = existing.id

    db.add(item)
    db.flush()

    # Count items in this batch
    total_count = db.query(func.count(BatchItem.id)).filter(BatchItem.batch_id == batch_id).scalar() or 0
    skipped_count = (
        db.query(func.count(BatchItem.id))
        .filter(BatchItem.batch_id == batch_id, BatchItem.status == BatchItemStatus.SKIPPED)
        .scalar()
        or 0
    )

    return batch_id, total_count, skipped_count


def get_pending_batch_id(db: Session) -> str | None:
    """Return the ID of the first pending batch, or None."""
    result = (
        db.query(BatchItem.batch_id)
        .filter(BatchItem.status == BatchItemStatus.PENDING)
        .group_by(BatchItem.batch_id)
        .first()
    )
    return result[0] if result else None


def get_batch_status(db: Session) -> dict[str, Any]:
    """Return status summary of the most recent batch."""
    # Find the most recent batch by created_at
    latest = db.query(BatchItem.batch_id).order_by(BatchItem.created_at.desc()).first()
    if not latest:
        return {"status": "empty"}

    batch_id = latest[0]

    # Count items by status
    status_counts = (
        db.query(BatchItem.status, func.count(BatchItem.id))
        .filter(BatchItem.batch_id == batch_id)
        .group_by(BatchItem.status)
        .all()
    )

    counts: dict[str, int] = {}
    total = 0
    for status_val, count in status_counts:
        counts[status_val.value if hasattr(status_val, "value") else str(status_val)] = count
        total += count

    # Determine overall batch status
    if counts.get("running", 0) > 0:
        overall = "running"
    elif counts.get("pending", 0) > 0:
        overall = "pending"
    elif counts.get("error", 0) > 0 and counts.get("done", 0) == 0:
        overall = "error"
    elif total > 0:
        overall = "done"
    else:
        overall = "empty"

    return {
        "batch_id": batch_id,
        "status": overall,
        "total": total,
        "counts": counts,
    }


def clear_completed(db: Session, batch_id: str | None = None) -> None:
    """Delete ALL batch_items (done, skipped, error, AND pending).

    Called before starting a new batch to ensure a clean slate.
    Pending items from old batches would otherwise accumulate and
    cause the batch to exceed the max_batch_size limit.
    """
    q = db.query(BatchItem)
    if batch_id:
        q = q.filter(BatchItem.batch_id == batch_id)
    q.delete(synchronize_session="fetch")
    db.commit()


def run_batch(batch_id: str, db: Session, user_id: UUID, cache: CacheService | None = None) -> None:
    """Process all pending items in a batch (runs as background task)."""
    items = (
        db.query(BatchItem).filter(BatchItem.batch_id == batch_id, BatchItem.status == BatchItemStatus.PENDING).all()
    )
    if not items:
        return

    cv = get_latest_cv(db, user_id)
    if not cv:
        # Mark all items as error
        for item in items:
            item.status = BatchItemStatus.ERROR  # type: ignore[assignment]
            item.error_message = "No CV found"  # type: ignore[assignment]
        db.commit()
        return

    for item in items:
        item.status = BatchItemStatus.RUNNING  # type: ignore[assignment]
        db.commit()

        try:
            # Re-check dedup (race condition safety)
            model_id = MODELS.get(cast(str, item.model) or "haiku", MODELS["haiku"])
            existing = find_existing_analysis(db, cast(str, item.content_hash), model_id)
            if existing:
                item.status = BatchItemStatus.DONE  # type: ignore[assignment]
                item.analysis_id = existing.id
                db.commit()
                continue

            # Run analysis with a hard timeout to prevent stalls on free tier.
            # Haiku responds in 3-5s; if it takes >45s, the call is stuck.
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    run_analysis,
                    db,
                    cast(str, cv.raw_text),
                    cast(UUID, cv.id),
                    cast(str, item.job_description),
                    cast(str, item.job_url) or "",
                    cast(str, item.model) or "haiku",
                    cache,
                )
                try:
                    analysis, result = future.result(timeout=_BATCH_ITEM_TIMEOUT)
                except FuturesTimeoutError:
                    future.cancel()
                    raise TimeoutError(f"Analysis timed out after {_BATCH_ITEM_TIMEOUT}s") from None

            add_spending(
                db,
                result.get("cost_usd", 0.0),
                result.get("tokens", {}).get("input", 0),
                result.get("tokens", {}).get("output", 0),
            )

            item.status = BatchItemStatus.DONE  # type: ignore[assignment]
            item.analysis_id = analysis.id
            item.attempt_count = (item.attempt_count or 0) + 1  # type: ignore[assignment]
            db.commit()
            logger.info("Batch item done: %s (%s)", item.preview, item.id)

            # Throttle between API calls to avoid shared-CPU
            # throttling and Anthropic rate limits.
            # 8s keeps CPU utilization ~33% — safe for free tier.
            time.sleep(8)

        except Exception as exc:
            db.rollback()
            item.status = BatchItemStatus.ERROR  # type: ignore[assignment]
            item.error_message = str(exc)  # type: ignore[assignment]
            item.attempt_count = (item.attempt_count or 0) + 1  # type: ignore[assignment]
            db.commit()
            logger.warning("Batch item error: %s — %s", item.preview, exc)


def batch_results(db: Session, batch_id: str) -> list[BatchItem]:
    """Return all items for a batch, ordered by creation time."""
    return db.query(BatchItem).filter(BatchItem.batch_id == batch_id).order_by(BatchItem.created_at.asc()).all()
