"""Batch analysis routes."""

from typing import cast
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import JSONResponse

from ..analysis.service import get_analysis_by_id, rebuild_result
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


@router.get("/results")
def batch_results(user: CurrentUser, db: DbSession) -> JSONResponse:
    """Return structured analysis data for all completed batch items."""
    batch = get_batch_status()
    if batch.get("status") == "empty":
        return JSONResponse({"status": "empty", "results": [], "total": 0})

    results = []
    total_cost = 0.0

    for item in batch.get("items", []):
        analysis_id = item.get("analysis_id")
        if item.get("status") != "done" or not analysis_id:
            continue

        analysis = get_analysis_by_id(db, analysis_id)
        if not analysis:
            continue

        full = rebuild_result(analysis)
        results.append(
            {
                "id": str(analysis.id),
                "job_title": analysis.role,
                "company": analysis.company,
                "location": analysis.location,
                "work_mode": analysis.work_mode,
                "score": analysis.score,
                "score_label": full.get("score_label", _score_label(analysis.score)),
                "recommendation": analysis.recommendation,
                "strengths": (analysis.strengths or [])[:3],
                "gaps": (analysis.gaps or [])[:3],
                "job_url": analysis.job_url,
                "source": item.get("source", ""),
                "model_used": analysis.model_used,
                "cost_usd": analysis.cost_usd or 0.0,
                "analyzed_at": analysis.created_at.isoformat() if analysis.created_at else "",
                "status": str(analysis.status),
            }
        )
        total_cost += analysis.cost_usd or 0.0

    results.sort(key=lambda r: r["score"], reverse=True)

    return JSONResponse(
        {
            "batch_id": batch.get("batch_id", ""),
            "batch_status": batch.get("status", ""),
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
def batch_clear(user: CurrentUser) -> JSONResponse:
    """Clear completed and pending batches from memory."""
    clear_completed()
    return JSONResponse({"ok": True})
