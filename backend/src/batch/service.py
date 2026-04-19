"""Batch analysis service.

Manages a persistent queue of job descriptions to analyze sequentially.
State is stored in PostgreSQL via the BatchItem model.
"""

import logging
import time
import uuid as uuid_mod
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from datetime import UTC, datetime, timedelta
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
# Haiku typically responds in 3-5s. On Render (no CPU throttle)
# allow up to 90s for slow API responses before skipping.
_BATCH_ITEM_TIMEOUT = 90

# Any item stuck in RUNNING longer than this is considered orphaned
# (e.g. the worker died mid-batch on deploy/SIGTERM).
_STALE_RUNNING_THRESHOLD_MINUTES = 10


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
    """Return status summary of the most recent batch, with per-item details."""
    # Find the most recent batch by created_at
    latest = db.query(BatchItem.batch_id).order_by(BatchItem.created_at.desc()).first()
    if not latest:
        return {"status": "empty", "items": []}

    batch_id = latest[0]

    items_rows = db.query(BatchItem).filter(BatchItem.batch_id == batch_id).order_by(BatchItem.created_at.asc()).all()

    counts: dict[str, int] = {}
    items: list[dict[str, Any]] = []
    for item in items_rows:
        status_key = item.status.value if hasattr(item.status, "value") else str(item.status)
        counts[status_key] = counts.get(status_key, 0) + 1
        jd = item.job_description or ""
        preview = item.preview or (jd[:80] + "..." if len(jd) > 80 else jd)
        items.append(
            {
                "id": str(item.id),
                "status": status_key,
                "preview": preview,
                "analysis_id": str(item.analysis_id) if item.analysis_id else None,
                "error_message": item.error_message,
            }
        )
    total = len(items_rows)

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
        "items": items,
    }


def clear_completed(db: Session, batch_id: str | None = None) -> int:
    """Delete batch_items, but never touch items currently RUNNING.

    Without the RUNNING guard, calling `/batch/clear` while a batch_run
    background task is mid-loop would orphan in-flight items (deleted rows
    while a worker still holds them in memory) and lose partial results.

    Returns the number of deleted rows.
    """
    q = db.query(BatchItem).filter(BatchItem.status != BatchItemStatus.RUNNING)
    if batch_id:
        q = q.filter(BatchItem.batch_id == batch_id)
    deleted = q.delete(synchronize_session="fetch")
    db.commit()
    return int(deleted or 0)


def cleanup_stale_running(db: Session, threshold_minutes: int = _STALE_RUNNING_THRESHOLD_MINUTES) -> int:
    """Mark any item stuck in RUNNING longer than threshold as ERROR.

    Called on app startup to recover from crashes/deploys that killed a
    batch worker mid-loop. Without this, items stay RUNNING forever and
    `get_batch_status` reports the batch as still active.

    Returns the number of items recovered.
    """
    threshold = datetime.now(UTC) - timedelta(minutes=threshold_minutes)
    stale = (
        db.query(BatchItem)
        .filter(
            BatchItem.status == BatchItemStatus.RUNNING,
            BatchItem.updated_at < threshold,
        )
        .all()
    )
    for item in stale:
        item.status = BatchItemStatus.ERROR  # type: ignore[assignment]
        item.error_message = f"stale_running_recovered_after_{threshold_minutes}m"  # type: ignore[assignment]
    if stale:
        db.commit()
        # Info, not warning: a small set of RUNNING items after a SIGTERM
        # redeploy is expected (background tasks can't drain gracefully).
        # The recovery ran successfully — no Sentry page needed. If the count
        # grows unexpectedly, elevate to warning and investigate.
        logger.info("Recovered %d stale RUNNING batch items on startup", len(stale))
    return len(stale)


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

    # One ThreadPoolExecutor for the whole batch instead of one per item.
    # The previous "with" inside the loop paid thread-lifecycle overhead
    # on every iteration — relevant on Render free tier (512MB shared vCPU).
    with ThreadPoolExecutor(max_workers=1) as executor:
        for item in items:
            item.status = BatchItemStatus.RUNNING  # type: ignore[assignment]
            db.commit()

            item_started_at = time.monotonic()
            ch_short = (cast(str, item.content_hash) or "")[:8]

            try:
                # Re-check dedup (race condition safety)
                model_id = MODELS.get(cast(str, item.model) or "haiku", MODELS["haiku"])
                existing = find_existing_analysis(db, cast(str, item.content_hash), model_id)
                if existing:
                    # Dedup hit discovered at run time → SKIPPED, not DONE.
                    # DONE means "this batch produced a fresh analysis";
                    # SKIPPED means "we reused an earlier one".
                    item.status = BatchItemStatus.SKIPPED  # type: ignore[assignment]
                    item.analysis_id = existing.id
                    db.commit()
                    logger.info("batch_item skipped (dedup) hash=%s preview=%r", ch_short, item.preview)
                    continue

                # Hard timeout prevents stuck API calls from blocking the batch.
                # Haiku responds in 3-5s; the 90s ceiling catches real stalls.
                future = executor.submit(
                    run_analysis,
                    db,
                    cast(str, cv.raw_text),
                    cast(UUID, cv.id),
                    cast(str, item.job_description),
                    cast(str, item.job_url) or "",
                    cast(str, item.model) or "haiku",
                    cache,
                    user_id,
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

                duration_ms = int((time.monotonic() - item_started_at) * 1000)
                tokens = result.get("tokens", {}) or {}
                logger.info(
                    "batch_item done hash=%s duration_ms=%d cost_usd=%.6f "
                    "tokens_in=%d tokens_out=%d model=%s preview=%r",
                    ch_short,
                    duration_ms,
                    float(result.get("cost_usd", 0.0)),
                    int(tokens.get("input", 0)),
                    int(tokens.get("output", 0)),
                    cast(str, item.model) or "haiku",
                    item.preview,
                )

                # Throttle between API calls to respect Anthropic rate limits.
                time.sleep(4)

            except Exception as exc:
                db.rollback()
                item.status = BatchItemStatus.ERROR  # type: ignore[assignment]
                item.error_message = str(exc)  # type: ignore[assignment]
                item.attempt_count = (item.attempt_count or 0) + 1  # type: ignore[assignment]
                db.commit()
                duration_ms = int((time.monotonic() - item_started_at) * 1000)
                logger.warning(
                    "batch_item error hash=%s duration_ms=%d preview=%r — %s",
                    ch_short,
                    duration_ms,
                    item.preview,
                    exc,
                )


def batch_results(db: Session, batch_id: str) -> list[BatchItem]:
    """Return all items for a batch, ordered by creation time."""
    return db.query(BatchItem).filter(BatchItem.batch_id == batch_id).order_by(BatchItem.created_at.asc()).all()
