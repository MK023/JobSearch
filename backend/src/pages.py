"""Page routes for the multi-page frontend (SSR)."""

from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from .analysis.models import AnalysisSource, AnalysisStatus
from .analysis.service import get_recent_analyses
from .cv.service import get_latest_cv
from .dashboard.service import get_db_usage, get_followup_alerts, get_spending
from .dependencies import CurrentUser, DbSession
from .metrics.service import cleanup_old_metrics, get_metrics_summary
from .notification_center.service import get_notifications, get_unread_count

router = APIRouter(tags=["pages"])


def _flash(request: Request) -> dict[str, Any]:
    """Pop flash messages from the session."""
    return {
        "error": request.session.pop("flash_error", None),
        "message": request.session.pop("flash_message", None),
    }


def _parse_since(request: Request) -> Any:
    """Parse ?since=<ISO> query param — used by aggregated notification
    drill-downs to let the destination page highlight items that were
    in the original aggregation. Silent fallback to None on malformed
    input (the highlight is a UI nicety, not a correctness requirement).
    """
    raw = request.query_params.get("since")
    if not raw:
        return None
    from datetime import datetime

    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _base_ctx(db: DbSession, user: CurrentUser, active_page: str) -> dict[str, Any]:
    """Context keys injected on EVERY page render.

    Sidebar badges: unread notifications, upcoming interviews, pending
    analyses waiting review (so the user sees the Storico backlog count
    from any page without having to land there first).
    """
    from sqlalchemy import func as _func

    from .agenda.models import TodoItem
    from .analysis.models import JobAnalysis
    from .analytics_page.service import get_lock_state
    from .interview.service import get_upcoming_interviews

    pending_count = (
        db.query(_func.count(JobAnalysis.id)).filter(JobAnalysis.status == AnalysisStatus.PENDING.value).scalar() or 0
    )
    agenda_count = (
        db.query(_func.count(TodoItem.id)).filter(TodoItem.done == False).scalar() or 0  # noqa: E712
    )
    # Analytics badge piggybacks on the same unlock threshold that fires
    # the ANALYTICS_AVAILABLE notification rule — badge + notification
    # card appear and disappear together.
    analytics_lock = get_lock_state(db)
    analytics_available = bool(not analytics_lock.get("locked", True))
    return {
        "user": user,
        "active_page": active_page,
        "notification_count": get_unread_count(db),
        "interview_count": len(get_upcoming_interviews(db, days=14)),
        "pending_count": pending_count,
        "agenda_count": agenda_count,
        "analytics_available": analytics_available,
    }


@router.get("/", response_class=HTMLResponse)
def dashboard_page(
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> Response:
    """Render the main dashboard with stats, recent analyses, and alerts."""
    from .dashboard.snapshot import build_dashboard_context

    templates = request.app.state.templates
    flash = _flash(request)
    widgets_ctx = build_dashboard_context(db, user)
    return templates.TemplateResponse(  # type: ignore[no-any-return]
        request,
        "dashboard.html",
        {
            **_base_ctx(db, user, "dashboard"),
            **widgets_ctx,
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
    batch = get_batch_status(db)

    return templates.TemplateResponse(  # type: ignore[no-any-return]
        request,
        "analyze.html",
        {
            **_base_ctx(db, user, "analyze"),
            "cv": cv,
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

    analyses = get_recent_analyses(db, limit=300)
    counts: dict[str, int] = {}
    for status in AnalysisStatus:
        counts[status.value] = sum(1 for a in analyses if a.status == status)

    return templates.TemplateResponse(  # type: ignore[no-any-return]
        request,
        "history.html",
        {
            **_base_ctx(db, user, "history"),
            "analyses": analyses,
            "counts": counts,
            "since_ts": _parse_since(request),
            "since_source": request.query_params.get("source"),
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
    from .interview.service import format_date, format_time

    upcoming = [
        {
            "interview_id": str(i.id),
            "analysis_id": str(a.id),
            "company": a.company,
            "role": a.role,
            "round_number": i.round_number,
            "scheduled_at": i.scheduled_at.isoformat(),
            "ends_at": i.ends_at.isoformat() if i.ends_at else None,
            "date_display": format_date(i.scheduled_at),
            "time_display": format_time(i.scheduled_at, i.ends_at),
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
            **_base_ctx(db, user, "interviews"),
            "upcoming_interviews": upcoming,
            "past_interviews": past_rows,
            "since_ts": _parse_since(request),
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
    """Render the settings page with CV, spending, preferences, and diagnostics."""
    import time

    from .agenda.models import TodoItem
    from .audit.models import AuditLog
    from .notification_center.models import NotificationDismissal
    from .preferences.service import get_preference

    templates = request.app.state.templates
    flash = _flash(request)

    cv = get_latest_cv(db, cast(UUID, user.id))
    spending = get_spending(db)
    db_usage = get_db_usage(db)

    # Operational parameters (from preferences, with defaults from config)
    from .config import settings as app_cfg

    prefs = {
        "followup_reminder_days": get_preference(db, "followup_reminder_days", app_cfg.followup_reminder_days),
        "budget_warning_threshold": get_preference(db, "budget_warning_threshold", 1.00),
        "budget_critical_threshold": get_preference(db, "budget_critical_threshold", 0.50),
        "interview_no_outcome_days": get_preference(db, "interview_no_outcome_days", 3),
    }

    # Maintenance counts
    completed_todos = db.query(TodoItem).filter(TodoItem.done == True).count()  # noqa: E712
    dismissed_count = db.query(NotificationDismissal).count()

    # Diagnostics
    recent_audit = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(10).all()

    startup_time = getattr(request.app.state, "_startup_time", None)
    uptime_str = ""
    if startup_time:
        up = int(time.time() - startup_time)
        hours, remainder = divmod(up, 3600)
        minutes, secs = divmod(remainder, 60)
        uptime_str = f"{hours}h {minutes}m {secs}s"

    return templates.TemplateResponse(  # type: ignore[no-any-return]
        request,
        "settings.html",
        {
            **_base_ctx(db, user, "settings"),
            "cv": cv,
            "spending": spending,
            "db_usage": db_usage,
            "prefs": prefs,
            "completed_todos": completed_todos,
            "dismissed_count": dismissed_count,
            "recent_audit": recent_audit,
            "uptime": uptime_str,
            "error": flash["error"],
            "message": flash["message"],
        },
    )


@router.get("/notifications", response_class=HTMLResponse)
def notifications_page(
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> Response:
    """Render the in-app notification center."""
    templates = request.app.state.templates
    flash = _flash(request)

    notifications = get_notifications(db)

    return templates.TemplateResponse(  # type: ignore[no-any-return]
        request,
        "notifications.html",
        {
            **_base_ctx(db, user, "notifications"),
            "notifications": notifications,
            "error": flash["error"],
            "message": flash["message"],
        },
    )


@router.get("/stats", response_class=HTMLResponse)
def stats_page(
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> Response:
    """Render the stats / analytics page."""
    from .stats.service import get_stats

    templates = request.app.state.templates
    flash = _flash(request)

    cache = getattr(request.app.state, "cache", None)
    stats = get_stats(db, cache=cache)

    return templates.TemplateResponse(  # type: ignore[no-any-return]
        request,
        "stats.html",
        {
            **_base_ctx(db, user, "stats"),
            "stats": stats,
            "error": flash["error"],
            "message": flash["message"],
        },
    )


@router.get("/agenda", response_class=HTMLResponse)
def agenda_page(
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> Response:
    """Render the agenda page — action-oriented daily/weekly view."""
    from datetime import UTC, datetime, timedelta

    from .analysis.models import JobAnalysis
    from .interview.models import Interview
    from .interview.service import format_date, get_upcoming_interviews

    templates = request.app.state.templates
    flash = _flash(request)
    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Upcoming interviews (next 14 days)
    upcoming_interviews = get_upcoming_interviews(db, days=14)

    # Today's interviews (subset)
    tomorrow_start = today_start + timedelta(days=1)
    today_interviews = [iv for iv in upcoming_interviews if datetime.fromisoformat(iv["scheduled_at"]) < tomorrow_start]
    week_interviews = [iv for iv in upcoming_interviews if iv not in today_interviews]

    # Follow-up alerts
    followup_alerts = get_followup_alerts(db)

    # Pending analyses (Cowork only)
    pending_analyses = (
        db.query(JobAnalysis)
        .filter(
            JobAnalysis.status == AnalysisStatus.PENDING.value,
            JobAnalysis.source == AnalysisSource.COWORK.value,
        )
        .order_by(JobAnalysis.created_at.desc())
        .limit(10)
        .all()
    )

    # Candidature inviate oggi
    applied_today = (
        db.query(JobAnalysis)
        .filter(
            JobAnalysis.status == AnalysisStatus.APPLIED.value,
            JobAnalysis.applied_at >= today_start,
        )
        .order_by(JobAnalysis.applied_at.desc())
        .all()
    )

    # In attesa — colloqui passati con esito "passed", analisi ancora in INTERVIEW,
    # e nessun round futuro schedulato per quell'analisi
    waiting_rows = (
        db.query(Interview, JobAnalysis)
        .join(JobAnalysis, Interview.analysis_id == JobAnalysis.id)
        .filter(
            Interview.scheduled_at < now,
            Interview.outcome == "passed",
            JobAnalysis.status == AnalysisStatus.INTERVIEW.value,
        )
        .order_by(Interview.scheduled_at.desc())
        .all()
    )
    # Exclude analyses that already have a future round scheduled
    analyses_with_future = {
        str(r[0]) for r in db.query(Interview.analysis_id).filter(Interview.scheduled_at > now).all()
    }
    waiting = [
        {
            "analysis_id": str(a.id),
            "company": a.company,
            "role": a.role,
            "interview_type": i.interview_type,
            "date_display": format_date(i.scheduled_at),
            "round_number": i.round_number,
        }
        for i, a in waiting_rows
        if str(a.id) not in analyses_with_future
    ]

    from .agenda.models import TodoItem
    from .agenda.service import get_virtual_triage_todos

    todos = db.query(TodoItem).order_by(TodoItem.done, TodoItem.created_at.desc()).all()
    triage_todos = get_virtual_triage_todos(db, cast(UUID, user.id))

    _days_it = ["Lunedi", "Martedi", "Mercoledi", "Giovedi", "Venerdi", "Sabato", "Domenica"]
    _months_it = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]
    today_display = f"{_days_it[now.weekday()]} {now.day:02d}/{now.month:02d}/{now.year}"

    return templates.TemplateResponse(  # type: ignore[no-any-return]
        request,
        "agenda.html",
        {
            **_base_ctx(db, user, "agenda"),
            "today_display": today_display,
            "today_interviews": today_interviews,
            "week_interviews": week_interviews,
            "followup_alerts": followup_alerts,
            "pending_analyses": pending_analyses,
            "applied_today": applied_today,
            "waiting": waiting,
            "todos": todos,
            "triage_todos": triage_todos,
            "since_ts": _parse_since(request),
            "error": flash["error"],
            "message": flash["message"],
        },
    )


@router.get("/news", response_class=HTMLResponse)
def news_page(
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> Response:
    """Render the company news page — cached news for active candidatures."""
    from .analysis.models import JobAnalysis
    from .integrations.news import get_cached_news

    templates = request.app.state.templates
    flash = _flash(request)

    # Get distinct companies from active candidatures (candidato + colloquio)
    active_statuses = [AnalysisStatus.APPLIED.value, AnalysisStatus.INTERVIEW.value]
    companies: list[str] = sorted(
        {
            r[0]
            for r in db.query(JobAnalysis.company)
            .filter(JobAnalysis.status.in_(active_statuses), JobAnalysis.company.isnot(None), JobAnalysis.company != "")
            .distinct()
            .all()
        }
    )

    # Read from cache only — news are populated during analysis enrichment
    news_groups = get_cached_news(companies, db)

    return templates.TemplateResponse(  # type: ignore[no-any-return]
        request,
        "news.html",
        {
            **_base_ctx(db, user, "news"),
            "news_groups": news_groups,
            "error": flash["error"],
            "message": flash["message"],
        },
    )


@router.get("/admin", response_class=HTMLResponse)
def admin_page(
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> Response:
    """Render the admin metrics dashboard."""
    templates = request.app.state.templates
    flash = _flash(request)

    # Cleanup old metrics on page load (cheap, idempotent)
    cleanup_old_metrics(db)

    metrics = get_metrics_summary(db)

    return templates.TemplateResponse(  # type: ignore[no-any-return]
        request,
        "admin.html",
        {
            **_base_ctx(db, user, "admin"),
            "metrics": metrics,
            "error": flash["error"],
            "message": flash["message"],
        },
    )
