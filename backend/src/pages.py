"""Page routes for the multi-page frontend (SSR)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from .analysis.models import AnalysisStatus
from .analysis.service import get_recent_analyses
from .auth.models import User
from .cv.service import get_latest_cv
from .dashboard.service import get_dashboard, get_followup_alerts, get_spending
from .database import get_db
from .dependencies import get_current_user
from .interview.service import get_upcoming_interviews

router = APIRouter(tags=["pages"])


def _flash(request: Request) -> dict:
    """Pop flash messages from the session."""
    return {
        "error": request.session.pop("flash_error", None),
        "message": request.session.pop("flash_message", None),
    }


@router.get("/", response_class=HTMLResponse)
def dashboard_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    templates = request.app.state.templates
    flash = _flash(request)

    dashboard = get_dashboard(db)
    spending = get_spending(db)
    analyses = get_recent_analyses(db, limit=5)
    followup_alerts = get_followup_alerts(db)
    upcoming_interviews = get_upcoming_interviews(db)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "active_page": "dashboard",
            "dashboard": dashboard,
            "spending": spending,
            "analyses": analyses,
            "followup_alerts": followup_alerts,
            "upcoming_interviews": upcoming_interviews,
            "error": flash["error"],
            "message": flash["message"],
        },
    )


@router.get("/analyze", response_class=HTMLResponse)
def analyze_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from .batch.service import get_batch_status

    templates = request.app.state.templates
    flash = _flash(request)

    cv = get_latest_cv(db, user.id)
    spending = get_spending(db)
    batch = get_batch_status()

    return templates.TemplateResponse(
        "analyze.html",
        {
            "request": request,
            "user": user,
            "active_page": "analyze",
            "cv": cv,
            "spending": spending,
            "batch": batch,
            "error": flash["error"],
            "message": flash["message"],
        },
    )


@router.get("/history", response_class=HTMLResponse)
def history_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    templates = request.app.state.templates
    flash = _flash(request)

    analyses = get_recent_analyses(db, limit=50)
    counts = {}
    for status in AnalysisStatus:
        counts[status.value] = sum(1 for a in analyses if a.status == status)

    return templates.TemplateResponse(
        "history.html",
        {
            "request": request,
            "user": user,
            "active_page": "history",
            "analyses": analyses,
            "counts": counts,
            "error": flash["error"],
            "message": flash["message"],
        },
    )


@router.get("/interviews", response_class=HTMLResponse)
def interviews_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from datetime import UTC, datetime

    from .interview.models import Interview

    templates = request.app.state.templates
    flash = _flash(request)

    upcoming = get_upcoming_interviews(db)

    now = datetime.now(UTC)
    past_rows = (
        db.query(Interview)
        .filter(Interview.scheduled_at <= now)
        .order_by(Interview.scheduled_at.desc())
        .all()
    )

    return templates.TemplateResponse(
        "interviews.html",
        {
            "request": request,
            "user": user,
            "active_page": "interviews",
            "upcoming_interviews": upcoming,
            "past_interviews": past_rows,
            "error": flash["error"],
            "message": flash["message"],
        },
    )


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    templates = request.app.state.templates
    flash = _flash(request)

    cv = get_latest_cv(db, user.id)
    spending = get_spending(db)

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "user": user,
            "active_page": "settings",
            "cv": cv,
            "spending": spending,
            "error": flash["error"],
            "message": flash["message"],
        },
    )
