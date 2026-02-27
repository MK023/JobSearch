"""Analysis JSON API routes (status changes, deletion, AJAX analysis)."""

from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..audit.service import audit
from ..auth.models import User
from ..config import settings
from ..cover_letter.models import CoverLetter
from ..cv.service import get_latest_cv
from ..dashboard.service import add_spending, check_budget_available, remove_spending
from ..database import get_db
from ..dependencies import get_cache, get_current_user
from ..integrations.anthropic_client import MODELS, content_hash
from ..integrations.cache import CacheService
from ..rate_limit import limiter
from .models import AnalysisStatus
from .service import find_existing_analysis, get_analysis_by_id, run_analysis, update_status

router = APIRouter(tags=["analysis-api"])


class AnalyzeRequest(BaseModel):
    job_description: str
    job_url: str = ""
    model: str = "haiku"


@router.post("/analyze")
@limiter.limit(settings.rate_limit_analyze)
def analyze_api(
    request: Request,
    body: AnalyzeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    cache: CacheService = Depends(get_cache),
):
    """Run analysis via JSON API (AJAX). Returns redirect URL."""
    cv = get_latest_cv(db, user.id)
    if not cv:
        return JSONResponse({"error": "Salva prima il tuo CV!"}, status_code=400)

    if len(body.job_description) > settings.max_job_desc_size:
        return JSONResponse(
            {"error": f"Descrizione troppo lunga (max {settings.max_job_desc_size} caratteri)"},
            status_code=400,
        )

    budget_ok, budget_msg = check_budget_available(db)
    if not budget_ok:
        return JSONResponse({"error": budget_msg}, status_code=400)

    ch = content_hash(cv.raw_text, body.job_description)
    model_id = MODELS.get(body.model, MODELS["haiku"])
    existing = find_existing_analysis(db, ch, model_id)

    if existing:
        audit(db, request, "analyze_cache", f"id={existing.id}")
        db.commit()
        return JSONResponse({"ok": True, "redirect": f"/analysis/{existing.id}", "cached": True})

    try:
        analysis, result = run_analysis(db, cv.raw_text, cv.id, body.job_description, body.job_url, body.model, cache)
        add_spending(
            db,
            result.get("cost_usd", 0.0),
            result.get("tokens", {}).get("input", 0),
            result.get("tokens", {}).get("output", 0),
        )
        audit(db, request, "analyze", f"id={analysis.id}, company={analysis.company}, score={analysis.score}")
        db.commit()
    except Exception as exc:
        db.rollback()
        audit(db, request, "analyze_error", str(exc))
        db.commit()
        return JSONResponse({"error": f"Analisi AI fallita: {exc}"}, status_code=500)

    return JSONResponse({"ok": True, "redirect": f"/analysis/{analysis.id}"})


@router.post("/status/{analysis_id}/{new_status}")
def change_status(
    request: Request,
    analysis_id: str,
    new_status: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        status_enum = AnalysisStatus(new_status)
    except ValueError:
        return JSONResponse({"error": "invalid status"}, status_code=400)

    analysis = get_analysis_by_id(db, analysis_id)
    if not analysis:
        return JSONResponse({"error": "not found"}, status_code=404)

    update_status(db, analysis, status_enum)
    audit(db, request, "status_change", f"id={analysis_id}, status={new_status}")
    db.commit()
    return JSONResponse({"ok": True, "status": new_status})


@router.delete("/analysis/{analysis_id}")
def delete_analysis(
    request: Request,
    analysis_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    analysis = get_analysis_by_id(db, analysis_id)
    if not analysis:
        return JSONResponse({"error": "Analysis not found"}, status_code=404)

    today = date.today()

    cover_letters = db.query(CoverLetter).filter(CoverLetter.analysis_id == analysis.id).all()
    for cl in cover_letters:
        cl_today = cl.created_at and cl.created_at.date() == today
        remove_spending(
            db, cl.cost_usd or 0, cl.tokens_input or 0, cl.tokens_output or 0, is_analysis=False, created_today=cl_today
        )

    a_today = analysis.created_at and analysis.created_at.date() == today
    remove_spending(
        db,
        analysis.cost_usd or 0,
        analysis.tokens_input or 0,
        analysis.tokens_output or 0,
        is_analysis=True,
        created_today=a_today,
    )

    audit(db, request, "delete_analysis", f"id={analysis_id}, {analysis.role} @ {analysis.company}")
    db.delete(analysis)
    db.commit()

    return JSONResponse({"ok": True})
