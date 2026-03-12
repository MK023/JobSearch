"""Batch analysis routes."""

from typing import cast
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import JSONResponse

from ..audit.service import audit
from ..config import settings
from ..dashboard.service import check_budget_available
from ..database import SessionLocal
from ..dependencies import Cache, CurrentUser, DbSession
from ..rate_limit import limiter
from .service import add_to_queue, clear_completed, get_batch_status, get_pending_batch_id, run_batch

router = APIRouter(prefix="/batch", tags=["batch"])


@router.post("/add")
def batch_add(
    request: Request,
    user: CurrentUser,
    db: DbSession,
    job_description: str = Form(...),
    job_url: str = Form(""),
    model: str = Form("haiku"),
) -> JSONResponse:
    """Add a job description to the pending batch queue."""
    if len(job_description) > settings.max_job_desc_size:
        return JSONResponse(
            {"error": f"Descrizione troppo lunga (max {settings.max_job_desc_size} caratteri)"}, status_code=400
        )

    batch_id, count = add_to_queue(job_description, job_url, model)
    audit(db, request, "batch_add", f"batch={batch_id}, count={count}")
    db.commit()
    return JSONResponse({"ok": True, "batch_id": batch_id, "count": count})


@router.post("/run")
@limiter.limit(settings.rate_limit_analyze)
def batch_run(
    request: Request,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    cache: Cache,
    db: DbSession,
) -> JSONResponse:
    """Start processing the pending batch queue in the background."""
    batch_id = get_pending_batch_id()
    if not batch_id:
        return JSONResponse({"error": "No pending batch"}, status_code=400)

    budget_ok, budget_msg = check_budget_available(db)
    if not budget_ok:
        return JSONResponse({"error": budget_msg}, status_code=400)

    def _run_in_background() -> None:
        bg_db = SessionLocal()
        try:
            run_batch(batch_id, bg_db, cast(UUID, user.id), cache)
        finally:
            bg_db.close()

    background_tasks.add_task(_run_in_background)
    audit(db, request, "batch_run", f"batch={batch_id}")
    db.commit()
    return JSONResponse({"ok": True, "batch_id": batch_id})


@router.get("/status")
def batch_status_route(user: CurrentUser) -> JSONResponse:
    """Return the current batch queue status."""
    return JSONResponse(get_batch_status())


@router.delete("/clear")
def batch_clear(user: CurrentUser) -> JSONResponse:
    """Clear completed and pending batches from memory."""
    clear_completed()
    return JSONResponse({"ok": True})
