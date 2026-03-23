"""Batch analysis routes."""

from typing import cast
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func

from ..analysis.service import get_analysis_by_id, rebuild_result
from ..audit.service import audit
from ..config import settings
from ..cv.service import get_latest_cv
from ..dashboard.service import check_budget_available
from ..database import SessionLocal
from ..dependencies import Cache, CurrentUser, DbSession, validate_uuid
from ..integrations.anthropic_client import MODELS
from ..rate_limit import limiter
from .models import BatchItem, BatchItemStatus
from .service import add_to_queue, batch_results, clear_completed, get_batch_status, get_pending_batch_id, run_batch

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

    # Hard limit: max items per batch (free tier constraint)
    pending_count = (
        db.query(func.count(BatchItem.id))
        .filter(BatchItem.status.in_([BatchItemStatus.PENDING, BatchItemStatus.RUNNING]))
        .scalar()
        or 0
    )
    if pending_count >= settings.max_batch_size:
        return JSONResponse(
            {
                "error": f"Batch pieno: massimo {settings.max_batch_size} offerte per batch. "
                f"Attualmente {pending_count} in coda. Attendi che finiscano o usa batch_clear()."
            },
            status_code=400,
        )

    cv = get_latest_cv(db, cast(UUID, user.id))
    if not cv:
        return JSONResponse({"error": "Nessun CV trovato. Carica un CV prima di usare il batch."}, status_code=400)

    batch_id, count, skipped = add_to_queue(
        db,
        cv_id=cast(UUID, cv.id),
        job_description=job_description,
        job_url=job_url,
        model=model,
        cv_text=cast(str, cv.raw_text),
    )
    audit(db, request, "batch_add", f"batch={batch_id}, count={count}, skipped={skipped}")
    db.commit()
    return JSONResponse({"ok": True, "batch_id": batch_id, "count": count, "skipped": skipped})


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
    batch_id = get_pending_batch_id(db)
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
def batch_status_route(user: CurrentUser, db: DbSession) -> JSONResponse:
    """Return the current batch queue status."""
    return JSONResponse(get_batch_status(db))


@router.get("/results")
def batch_results_route(user: CurrentUser, db: DbSession) -> JSONResponse:
    """Return structured analysis data for all completed batch items."""
    status = get_batch_status(db)
    if status.get("status") == "empty":
        return JSONResponse({"status": "empty", "results": [], "total": 0})

    batch_id = status["batch_id"]
    items = batch_results(db, batch_id)

    results = []
    total_cost = 0.0

    for item in items:
        if item.status not in (BatchItemStatus.DONE, BatchItemStatus.SKIPPED) or not item.analysis_id:
            continue

        analysis = get_analysis_by_id(db, str(item.analysis_id))
        if not analysis:
            continue

        full = rebuild_result(analysis)
        is_dedup = item.status == BatchItemStatus.SKIPPED
        results.append(
            {
                "id": str(analysis.id),
                "job_title": analysis.role,
                "company": analysis.company,
                "location": analysis.location,
                "work_mode": analysis.work_mode,
                "score": analysis.score,
                "score_label": full.get("score_label", _score_label(int(analysis.score or 0))),
                "recommendation": analysis.recommendation,
                "strengths": (analysis.strengths or [])[:3],
                "gaps": (analysis.gaps or [])[:3],
                "job_url": analysis.job_url,
                "model_used": analysis.model_used,
                "cost_usd": analysis.cost_usd or 0.0,
                "analyzed_at": analysis.created_at.isoformat() if analysis.created_at else "",
                "status": str(analysis.status),
                "is_duplicate": is_dedup,
            }
        )
        total_cost += float(analysis.cost_usd or 0.0)

    results.sort(key=lambda r: r["score"], reverse=True)

    return JSONResponse(
        {
            "batch_id": batch_id,
            "batch_status": status.get("status", ""),
            "total": len(results),
            "total_cost_usd": round(total_cost, 6),
            "results": results,
        }
    )


def _score_label(score: int) -> str:
    if score >= 80:
        return "ottimo"
    if score >= 60:
        return "buono"
    if score >= 40:
        return "discreto"
    return "basso"


@router.delete("/clear")
def batch_clear(user: CurrentUser, db: DbSession) -> JSONResponse:
    """Clear completed, skipped, and errored batch items from the database."""
    clear_completed(db)
    return JSONResponse({"ok": True})


@router.get("/pending-items")
def pending_items(
    user: CurrentUser,
    db: DbSession,
) -> JSONResponse:
    """Return all pending batch items plus CV text, so the MCP can process them locally."""
    batch_id = get_pending_batch_id(db)
    if not batch_id:
        return JSONResponse({"batch_id": None, "cv_text": "", "items": []})

    items = (
        db.query(BatchItem)
        .filter(BatchItem.batch_id == batch_id, BatchItem.status == BatchItemStatus.PENDING)
        .order_by(BatchItem.created_at.asc())
        .all()
    )

    cv = get_latest_cv(db, cast(UUID, user.id))
    cv_text = cast(str, cv.raw_text) if cv else ""

    items_out = []
    for item in items:
        model_key = cast(str, item.model) or "haiku"
        model_id = MODELS.get(model_key, MODELS["haiku"])
        items_out.append(
            {
                "id": str(item.id),
                "job_description": item.job_description,
                "job_url": item.job_url or "",
                "model": model_key,
                "model_id": model_id,
                "content_hash": item.content_hash,
            }
        )

    return JSONResponse({"batch_id": batch_id, "cv_text": cv_text, "items": items_out})


@router.post("/item/{item_id}/status")
def update_item_status(
    item_id: str,
    db: DbSession,
    user: CurrentUser,
    status: str = Form(...),
    analysis_id: str = Form(""),
    error_message: str = Form(""),
) -> JSONResponse:
    """Update a single batch item's status. Called by the MCP after each analysis."""
    uid = validate_uuid(item_id)

    item = db.query(BatchItem).filter(BatchItem.id == uid).first()
    if not item:
        return JSONResponse({"error": "Batch item not found"}, status_code=404)

    try:
        status_enum = BatchItemStatus(status)
    except ValueError:
        return JSONResponse({"error": "Invalid status"}, status_code=400)

    item.status = status_enum  # type: ignore[assignment]
    item.attempt_count = (item.attempt_count or 0) + 1  # type: ignore[assignment]

    if analysis_id:
        validated_aid = validate_uuid(analysis_id)
        item.analysis_id = validated_aid  # type: ignore[assignment]

    if error_message:
        item.error_message = error_message  # type: ignore[assignment]

    db.commit()
    return JSONResponse({"ok": True})
