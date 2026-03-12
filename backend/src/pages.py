"""Page routes for the multi-page frontend (SSR)."""

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from .analysis.models import AnalysisStatus
from .analysis.service import get_recent_analyses
from .cv.service import get_latest_cv
from .dashboard.service import get_dashboard, get_followup_alerts, get_spending
from .dependencies import CurrentUser, DbSession
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
    db: DbSession,
    user: CurrentUser,
) -> Response:
    """Render the main dashboard with stats, recent analyses, and alerts."""
    templates = request.app.state.templates
    flash = _flash(request)

    dashboard = get_dashboard(db)
    spending = get_spending(db)
    analyses = get_recent_analyses(db, limit=5)
    followup_alerts = get_followup_alerts(db)
    upcoming_interviews = get_upcoming_interviews(db)

    return templates.TemplateResponse(  # type: ignore[no-any-return]
        request,
        "dashboard.html",
        {
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
    db: DbSession,
    user: CurrentUser,
) -> Response:
    """Render the job analysis submission page."""
    from .batch.service import get_batch_status

    templates = request.app.state.templates
    flash = _flash(request)

    cv = get_latest_cv(db, cast(UUID, user.id))
    spending = get_spending(db)
    batch = get_batch_status()

    return templates.TemplateResponse(  # type: ignore[no-any-return]
        request,
        "analyze.html",
        {
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
    db: DbSession,
    user: CurrentUser,
) -> Response:
    """Render the analysis history page with status counts."""
    templates = request.app.state.templates
    flash = _flash(request)

    analyses = get_recent_analyses(db, limit=50)
    counts = {}
    for status in AnalysisStatus:
        counts[status.value] = sum(1 for a in analyses if a.status == status)

    return templates.TemplateResponse(  # type: ignore[no-any-return]
        request,
        "history.html",
        {
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
    db: DbSession,
    user: CurrentUser,
) -> Response:
    """Render the interviews page with upcoming and past interviews."""
    from datetime import UTC, datetime

    from .analysis.models import JobAnalysis
    from .interview.models import Interview

    templates = request.app.state.templates
    flash = _flash(request)

    now = datetime.now(UTC)

    # All future interviews (no 48h limit, unlike dashboard widget)
    upcoming_rows = (
        db.query(Interview, JobAnalysis)
        .join(JobAnalysis, Interview.analysis_id == JobAnalysis.id)
        .filter(Interview.scheduled_at > now)
        .order_by(Interview.scheduled_at.asc())
        .all()
    )
    from .interview.service import _format_date, _format_time

    upcoming = [
        {
            "analysis_id": str(a.id),
            "company": a.company,
            "role": a.role,
            "scheduled_at": i.scheduled_at.isoformat(),
            "ends_at": i.ends_at.isoformat() if i.ends_at else None,
            "date_display": _format_date(i.scheduled_at),
            "time_display": _format_time(i.scheduled_at, i.ends_at),
            "platform": i.platform,
            "interview_type": i.interview_type,
            "meeting_link": i.meeting_link,
        }
        for i, a in upcoming_rows
    ]

    past_rows = db.query(Interview).filter(Interview.scheduled_at <= now).order_by(Interview.scheduled_at.desc()).all()

    return templates.TemplateResponse(  # type: ignore[no-any-return]
        request,
        "interviews.html",
        {
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
    db: DbSession,
    user: CurrentUser,
) -> Response:
    """Render the settings page with CV and spending info."""
    templates = request.app.state.templates
    flash = _flash(request)

    cv = get_latest_cv(db, cast(UUID, user.id))
    spending = get_spending(db)

    return templates.TemplateResponse(  # type: ignore[no-any-return]
        request,
        "settings.html",
        {
            "user": user,
            "active_page": "settings",
            "cv": cv,
            "spending": spending,
            "error": flash["error"],
            "message": flash["message"],
        },
    )
