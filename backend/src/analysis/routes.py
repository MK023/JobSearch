"""Analysis HTML routes (SSR pages)."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..audit.service import audit
from ..auth.models import User
from ..cv.service import get_latest_cv
from ..dashboard.service import add_spending
from ..database import get_db
from ..dependencies import get_cache, get_current_user
from ..integrations.anthropic_client import MODELS, content_hash
from ..integrations.cache import CacheService
from .service import (
    find_existing_analysis,
    get_analysis_by_id,
    rebuild_result,
    run_analysis,
)

router = APIRouter(tags=["analysis"])


@router.post("/analyze", response_class=HTMLResponse)
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
        return _render_page(request, db, user, error="Salva prima il tuo CV!")

    ch = content_hash(cv.raw_text, job_description)
    model_id = MODELS.get(model, MODELS["haiku"])
    existing = find_existing_analysis(db, ch, model_id)

    if existing:
        audit(db, request, "analyze_cache", f"id={existing.id}")
        result = rebuild_result(existing, from_cache=True)
        msg = f"Analisi gia' eseguita il {existing.created_at.strftime('%d/%m/%Y %H:%M')} - mostro il risultato salvato"
        return _render_page(request, db, user, current=existing, result=result, message=msg)

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
        audit(db, request, "analyze_error", str(exc))
        db.commit()
        return _render_page(request, db, user, error=f"Analisi AI fallita: {exc}")

    return _render_page(request, db, user, current=analysis, result=result)


@router.get("/analysis/{analysis_id}", response_class=HTMLResponse)
def view_analysis(
    request: Request,
    analysis_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    analysis = get_analysis_by_id(db, analysis_id)
    if not analysis:
        return RedirectResponse(url="/", status_code=303)

    result = rebuild_result(analysis)
    return _render_page(request, db, user, current=analysis, result=result)


def _render_page(request: Request, db: Session, user: User, **extra) -> HTMLResponse:
    """Build the full page context and render index.html."""
    from ..analysis.service import get_recent_analyses
    from ..cv.service import get_latest_cv
    from ..dashboard.service import get_active_applications, get_dashboard, get_followup_alerts, get_spending
    from ..notifications.service import check_and_send_followup_reminders

    cv = get_latest_cv(db, user.id)
    analyses = get_recent_analyses(db)
    followup_alerts = get_followup_alerts(db)
    active_apps = get_active_applications(db)

    # Send any pending email notifications
    check_and_send_followup_reminders(db)

    dashboard = get_dashboard(db)
    spending = get_spending(db)

    ctx = {
        "request": request,
        "user": user,
        "cv": cv,
        "analyses": analyses,
        "spending": spending,
        "followup_alerts": followup_alerts,
        "dashboard": dashboard,
        "active_apps": active_apps,
    }
    ctx.update(extra)

    templates = request.app.state.templates
    return templates.TemplateResponse("index.html", ctx)
