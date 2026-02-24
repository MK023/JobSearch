"""Batch analysis service.

Manages a queue of job descriptions to analyze sequentially.
State is stored in-memory (lost on restart by design - batch is a session-level feature).
"""

import uuid as uuid_mod
from uuid import UUID

from sqlalchemy.orm import Session

from ..analysis.service import find_existing_analysis, run_analysis
from ..cv.service import get_latest_cv
from ..dashboard.service import add_spending
from ..integrations.anthropic_client import MODELS, content_hash
from ..integrations.cache import CacheService

# In-memory batch state (session-level, not persistent)
_batch_queue: dict[str, dict] = {}


def add_to_queue(job_description: str, job_url: str = "", model: str = "haiku") -> tuple[str, int]:
    """Add a job to the pending batch queue. Returns (batch_id, queue_size)."""
    active = None
    for bid, b in _batch_queue.items():
        if b["status"] == "pending":
            active = (bid, b)
            break

    if not active:
        bid = str(uuid_mod.uuid4())
        _batch_queue[bid] = {"items": [], "status": "pending"}
        active = (bid, _batch_queue[bid])

    active[1]["items"].append(
        {
            "job_description": job_description,
            "job_url": job_url,
            "model": model,
            "status": "pending",
            "preview": job_description[:80] + "..." if len(job_description) > 80 else job_description,
        }
    )
    return active[0], len(active[1]["items"])


def get_pending_batch_id() -> str | None:
    for bid, b in _batch_queue.items():
        if b["status"] == "pending":
            return bid
    return None


def get_batch_status() -> dict:
    for bid in reversed(list(_batch_queue.keys())):
        return {"batch_id": bid, **_batch_queue[bid]}
    return {"status": "empty"}


def clear_completed() -> None:
    to_remove = [bid for bid, b in _batch_queue.items() if b["status"] in ("pending", "done")]
    for bid in to_remove:
        del _batch_queue[bid]


def run_batch(batch_id: str, db: Session, user_id: UUID, cache: CacheService | None = None) -> None:
    """Process all items in a batch queue (runs as background task)."""
    batch = _batch_queue.get(batch_id)
    if not batch:
        return

    batch["status"] = "running"

    cv = get_latest_cv(db, user_id)
    if not cv:
        batch["status"] = "error"
        batch["error"] = "No CV found"
        return

    for _idx, item in enumerate(batch["items"], 1):
        if item["status"] == "cancelled":
            continue
        item["status"] = "running"
        try:
            ch = content_hash(cv.raw_text, item["job_description"])
            model_id = MODELS.get(item.get("model", "haiku"), MODELS["haiku"])

            existing = find_existing_analysis(db, ch, model_id)
            if existing:
                item["status"] = "done"
                item["result_preview"] = f"{existing.role} @ {existing.company} -- {existing.score}/100 (duplicate)"
                continue

            analysis, result = run_analysis(
                db,
                cv.raw_text,
                cv.id,
                item["job_description"],
                item.get("job_url", ""),
                item.get("model", "haiku"),
                cache,
            )
            add_spending(
                db,
                result.get("cost_usd", 0.0),
                result.get("tokens", {}).get("input", 0),
                result.get("tokens", {}).get("output", 0),
            )
            db.commit()
            item["status"] = "done"
            item["result_preview"] = (
                f"{result.get('role', '?')} @ {result.get('company', '?')} -- {result.get('score', 0)}/100"
            )

        except Exception as exc:
            db.rollback()
            item["status"] = "error"
            item["error"] = str(exc)

    batch["status"] = "done"
