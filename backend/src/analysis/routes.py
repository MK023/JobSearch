"""Analysis HTML routes (SSR pages)."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..audit.service import audit
from ..auth.models import User
from ..config import settings
from ..cv.service import get_latest_cv
from ..dashboard.service import add_spending, check_budget_available
from ..database import get_db
from ..dependencies import get_cache, get_current_user
from ..integrations.anthropic_client import MODELS, content_hash
from ..integrations.cache import CacheService
from ..rate_limit import limiter
from .service import (
    find_existing_analysis,
    get_analysis_by_id,
    rebuild_result,
    run_analysis,
)

router = APIRouter(tags=["analysis"])


@router.post("/analyze", response_class=HTMLResponse)
@limiter.limit(settings.rate_limit_analyze)
def analyze(
    request: Request,
    job_description: str = Form(...),
    job_url: str = Form(""),
    model: str = Form("haiku"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    cache: CacheService = Depends(get_cache),
):
    cv = get_latest_cv(db, user.id)

    if not cv:
        request.session["flash_error"] = "Salva prima il tuo CV!"
        return RedirectResponse(url="/analyze", status_code=303)

    # Input size validation
    if len(job_description) > settings.max_job_desc_size:
        request.session["flash_error"] = f"Descrizione troppo lunga (max {settings.max_job_desc_size} caratteri)"
        return RedirectResponse(url="/analyze", status_code=303)

    # Budget check
    budget_ok, budget_msg = check_budget_available(db)
    if not budget_ok:
        request.session["flash_error"] = budget_msg
        return RedirectResponse(url="/analyze", status_code=303)

    ch = content_hash(cv.raw_text, job_description)
    model_id = MODELS.get(model, MODELS["haiku"])
    existing = find_existing_analysis(db, ch, model_id)

    if existing:
        audit(db, request, "analyze_cache", f"id={existing.id}")
        request.session["flash_message"] = (
            f"Analisi gia' eseguita il {existing.created_at.strftime('%d/%m/%Y %H:%M')} - mostro il risultato salvato"
        )
        return RedirectResponse(url=f"/analysis/{existing.id}", status_code=303)

    try:
        analysis, result = run_analysis(db, cv.raw_text, cv.id, job_description, job_url, model, cache)
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
        request.session["flash_error"] = f"Analisi AI fallita: {exc}"
        return RedirectResponse(url="/analyze", status_code=303)

    return RedirectResponse(url=f"/analysis/{analysis.id}", status_code=303)


@router.get("/analysis/{analysis_id}", response_class=HTMLResponse)
def view_analysis(
    request: Request,
    analysis_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from ..contacts.service import get_contacts_for_analysis
    from ..interview.service import get_interview_by_analysis

    analysis = get_analysis_by_id(db, analysis_id)
    if not analysis:
        return RedirectResponse(url="/history", status_code=303)

    result = rebuild_result(analysis)
    interview = get_interview_by_analysis(db, analysis.id)
    cover_letter = analysis.cover_letters[0] if analysis.cover_letters else None
    contacts = get_contacts_for_analysis(db, str(analysis.id))

    error = request.session.pop("flash_error", None)
    message = request.session.pop("flash_message", None)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "analysis_detail.html",
        {
            "request": request,
            "user": user,
            "active_page": "history",
            "current": analysis,
            "result": result,
            "interview": interview,
            "cover_letter": cover_letter,
            "contacts": contacts,
            "error": error,
            "message": message,
        },
    )
