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
    source: str = "manual",
) -> tuple[str, int, int]:
    """Add a job to the pending batch queue.

    Before inserting, checks for existing analysis (dedup).
    Returns (batch_id, total_count, skipped_count).

    ``source`` flows through the queue → ``_execute_analysis`` →
    ``run_analysis`` so the resulting ``JobAnalysis`` carries the
    caller's origin (e.g. ``cowork`` for the MCP workflow). Defaults to
    ``manual`` for direct API/UI submissions.
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
        source=source,
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


def _status_key(item: BatchItem) -> str:
    """Return the enum-backed status value as a string."""
    return item.status.value if hasattr(item.status, "value") else str(item.status)


def _item_preview(item: BatchItem) -> str:
    """Derive a short preview for UI, falling back to a truncated description."""
    if item.preview:
        return cast(str, item.preview)
    jd = cast(str, item.job_description) or ""
    return f"{jd[:80]}..." if len(jd) > 80 else jd


def _item_dict(item: BatchItem, status_key: str) -> dict[str, Any]:
    """Serialize a BatchItem row for the status endpoint."""
    return {
        "id": str(item.id),
        "status": status_key,
        "preview": _item_preview(item),
        "analysis_id": str(item.analysis_id) if item.analysis_id else None,
        "error_message": item.error_message,
    }


def _overall_status(counts: dict[str, int], total: int) -> str:
    """Resolve the single-string overall batch status from per-status counts."""
    if counts.get("running", 0) > 0:
        return "running"
    if counts.get("pending", 0) > 0:
        return "pending"
    if counts.get("error", 0) > 0 and counts.get("done", 0) == 0:
        return "error"
    if total > 0:
        return "done"
    return "empty"


def get_batch_status(db: Session) -> dict[str, Any]:
    """Return status summary of the most recent batch, with per-item details."""
    latest = db.query(BatchItem.batch_id).order_by(BatchItem.created_at.desc()).first()
    if not latest:
        return {"status": "empty", "items": []}

    batch_id = latest[0]
    items_rows = db.query(BatchItem).filter(BatchItem.batch_id == batch_id).order_by(BatchItem.created_at.asc()).all()

    counts: dict[str, int] = {}
    items: list[dict[str, Any]] = []
    for item in items_rows:
        key = _status_key(item)
        counts[key] = counts.get(key, 0) + 1
        items.append(_item_dict(item, key))

    total = len(items_rows)
    return {
        "batch_id": batch_id,
        "status": _overall_status(counts, total),
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


def _mark_items_error(db: Session, items: list[BatchItem], message: str) -> None:
    """Mark a group of batch items as ERROR with the given message."""
    for item in items:
        item.status = BatchItemStatus.ERROR  # type: ignore[assignment]
        item.error_message = message  # type: ignore[assignment]
    db.commit()


def _try_skip_dedup(db: Session, item: BatchItem, ch_short: str) -> bool:
    """If an earlier analysis matches the item, mark it SKIPPED. Return True on skip."""
    model_id = MODELS.get(cast(str, item.model) or "haiku", MODELS["haiku"])
    existing = find_existing_analysis(db, cast(str, item.content_hash), model_id)
    if not existing:
        return False
    # Dedup hit discovered at run time → SKIPPED, not DONE.
    # DONE means "this batch produced a fresh analysis";
    # SKIPPED means "we reused an earlier one".
    item.status = BatchItemStatus.SKIPPED  # type: ignore[assignment]
    item.analysis_id = existing.id
    db.commit()
    logger.info("batch_item skipped (dedup) hash=%s preview=%r", ch_short, item.preview)
    return True


def _execute_analysis(
    executor: ThreadPoolExecutor,
    db: Session,
    item: BatchItem,
    cv: Any,
    cache: CacheService | None,
    user_id: UUID,
) -> tuple[Any, dict[str, Any]]:
    """Run the analysis under a hard timeout. Raises TimeoutError on stall."""
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
        cast(str, item.source) or "manual",
    )
    try:
        return future.result(timeout=_BATCH_ITEM_TIMEOUT)
    except FuturesTimeoutError:
        future.cancel()
        raise TimeoutError(f"Analysis timed out after {_BATCH_ITEM_TIMEOUT}s") from None


def _record_success(
    db: Session,
    item: BatchItem,
    analysis: Any,
    result: dict[str, Any],
    ch_short: str,
    started_at: float,
) -> None:
    """Mark the item DONE and log cost/latency."""
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

    duration_ms = int((time.monotonic() - started_at) * 1000)
    tokens = result.get("tokens", {}) or {}
    logger.info(
        "batch_item done hash=%s duration_ms=%d cost_usd=%.6f tokens_in=%d tokens_out=%d model=%s preview=%r",
        ch_short,
        duration_ms,
        float(result.get("cost_usd", 0.0)),
        int(tokens.get("input", 0)),
        int(tokens.get("output", 0)),
        cast(str, item.model) or "haiku",
        item.preview,
    )


def _record_failure(db: Session, item: BatchItem, exc: Exception, ch_short: str, started_at: float) -> None:
    """Rollback the in-flight transaction and mark the item ERROR."""
    db.rollback()
    item.status = BatchItemStatus.ERROR  # type: ignore[assignment]
    item.error_message = str(exc)  # type: ignore[assignment]
    item.attempt_count = (item.attempt_count or 0) + 1  # type: ignore[assignment]
    db.commit()
    duration_ms = int((time.monotonic() - started_at) * 1000)
    logger.warning(
        "batch_item error hash=%s duration_ms=%d preview=%r — %s",
        ch_short,
        duration_ms,
        item.preview,
        exc,
    )


def _process_one_item(
    executor: ThreadPoolExecutor,
    db: Session,
    item: BatchItem,
    cv: Any,
    cache: CacheService | None,
    user_id: UUID,
) -> None:
    """Run a single batch item end-to-end (dedup → execute → record)."""
    item.status = BatchItemStatus.RUNNING  # type: ignore[assignment]
    db.commit()

    started_at = time.monotonic()
    ch_short = (cast(str, item.content_hash) or "")[:8]

    try:
        if _try_skip_dedup(db, item, ch_short):
            return
        analysis, result = _execute_analysis(executor, db, item, cv, cache, user_id)
        _record_success(db, item, analysis, result, ch_short, started_at)
        # Throttle between API calls to respect Anthropic rate limits.
        time.sleep(4)
    except Exception as exc:
        _record_failure(db, item, exc, ch_short, started_at)


def run_batch(batch_id: str, db: Session, user_id: UUID, cache: CacheService | None = None) -> None:
    """Process all pending items in a batch (runs as background task)."""
    items = (
        db.query(BatchItem).filter(BatchItem.batch_id == batch_id, BatchItem.status == BatchItemStatus.PENDING).all()
    )
    if not items:
        return

    cv = get_latest_cv(db, user_id)
    if not cv:
        _mark_items_error(db, items, "No CV found")
        return

    # One ThreadPoolExecutor for the whole batch instead of one per item.
    # The previous "with" inside the loop paid thread-lifecycle overhead
    # on every iteration — relevant on Render free tier (512MB shared vCPU).
    with ThreadPoolExecutor(max_workers=1) as executor:
        for item in items:
            _process_one_item(executor, db, item, cv, cache, user_id)


def batch_results(db: Session, batch_id: str) -> list[BatchItem]:
    """Return all items for a batch, ordered by creation time."""
    return db.query(BatchItem).filter(BatchItem.batch_id == batch_id).order_by(BatchItem.created_at.asc()).all()
