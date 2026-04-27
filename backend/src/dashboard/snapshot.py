"""Dashboard snapshot — server-rendered partial HTML for live widget updates.

The homepage renders 9 widgets via Jinja partials at page-load. After
PR #191 the sidebar badges update live via SSE, but the dashboard cards
themselves stay frozen until the user reloads. This module exposes the
same widgets on a JSON endpoint so the client can swap each widget's
innerHTML without a full navigation.

Why render HTML server-side instead of returning JSON for the client to
template:
    The widget templates already exist as Jinja partials. Re-implementing
    them in JS would create two sources of truth that drift over time.
    Sending pre-rendered HTML keeps the SSR pipeline as the single owner
    of widget markup; the client just patches the DOM.

Why an in-memory cache:
    Neon free tier is at 80% capacity (see project memory). Each snapshot
    fans out to ~12 DB queries (followup, interviews, pending cowork,
    pending extension, top 5, db usage, news per active company, todos…).
    Without a cache, a Cowork burst (10 imports → 10 broadcast_sync calls
    → 10 client refresh requests) would multiply that fan-out by 10.

    A 5 s TTL absorbs bursts without hurting perceived freshness. The
    same TTL the sidebar counts use, so all live elements stay coherent.
"""

from __future__ import annotations

import time
from typing import Any, cast
from uuid import UUID

from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..analysis.models import AnalysisSource, AnalysisStatus, JobAnalysis
from ..auth.models import User

_WIDGET_PARTIALS: dict[str, str] = {
    "followup": "partials/dashboard/widget_followup.html",
    "interviews": "partials/dashboard/widget_interviews.html",
    "pending_cowork": "partials/dashboard/widget_pending_cowork.html",
    "activity_today": "partials/dashboard/widget_activity_today.html",
    "top_candidates": "partials/dashboard/widget_top_candidates.html",
    "inbox": "partials/dashboard/widget_inbox.html",
    "news": "partials/dashboard/widget_news.html",
    "todos": "partials/dashboard/widget_todos.html",
    "db_usage": "partials/dashboard/widget_db_usage.html",
}

_CACHE_TTL_SECONDS = 5.0
_cache: dict[str, Any] = {"value": None, "expires_at": 0.0}


def build_dashboard_context(db: Session, user: User) -> dict[str, Any]:
    """Build the same context dict the dashboard page uses to render widgets.

    Pulled out of ``pages.py::dashboard_page`` so the snapshot endpoint
    and the SSR view share one source of truth — no risk of drift if a
    widget gains a new variable.
    """
    from ..agenda.models import TodoItem
    from ..agenda.service import get_virtual_triage_todos
    from ..inbox.service import get_inbox_stats
    from ..integrations.news import get_cached_news
    from ..interview.service import get_upcoming_interviews
    from .service import get_dashboard, get_db_usage, get_followup_alerts, get_spending, get_top_candidates

    dashboard = get_dashboard(db)
    spending = get_spending(db)
    followup_alerts = get_followup_alerts(db)
    top_candidates = get_top_candidates(db, limit=5)
    db_usage = get_db_usage(db)
    upcoming_interviews = get_upcoming_interviews(db, days=14)
    inbox_stats = get_inbox_stats(db, cast(UUID, user.id))

    pending_analyses = (
        db.query(JobAnalysis)
        .filter(
            JobAnalysis.status == AnalysisStatus.PENDING.value,
            JobAnalysis.source == AnalysisSource.COWORK.value,
        )
        .order_by(JobAnalysis.created_at.desc())
        .limit(5)
        .all()
    )
    pending_extension = (
        db.query(JobAnalysis)
        .filter(
            JobAnalysis.status == AnalysisStatus.PENDING.value,
            JobAnalysis.source == AnalysisSource.EXTENSION.value,
        )
        .order_by(JobAnalysis.created_at.desc())
        .limit(5)
        .all()
    )

    active_statuses = [AnalysisStatus.APPLIED.value, AnalysisStatus.INTERVIEW.value]
    active_companies: list[str] = sorted(
        {
            r[0]
            for r in db.query(JobAnalysis.company)
            .filter(JobAnalysis.status.in_(active_statuses), JobAnalysis.company.isnot(None), JobAnalysis.company != "")
            .distinct()
            .all()
        }
    )
    all_news = get_cached_news(active_companies, db)
    recent_news = sorted(
        [{**a, "company": g["company"]} for g in all_news for a in g["articles"]],
        key=lambda x: x.get("published_at", ""),
        reverse=True,
    )[:5]

    agenda_todos = db.query(TodoItem).filter(TodoItem.done == False).order_by(TodoItem.created_at.desc()).limit(3).all()  # noqa: E712
    agenda_triage_todos = get_virtual_triage_todos(db, cast(UUID, user.id))[:3]

    return {
        "dashboard": dashboard,
        "spending": spending,
        "followup_alerts": followup_alerts,
        "upcoming_interviews": upcoming_interviews,
        "pending_analyses": pending_analyses,
        "pending_extension": pending_extension,
        "top_candidates": top_candidates,
        "db_usage": db_usage,
        "recent_news": recent_news,
        "agenda_todos": agenda_todos,
        "agenda_triage_todos": agenda_triage_todos,
        "inbox_stats": inbox_stats,
    }


def _render_snapshot(request: Request, templates: Jinja2Templates, context: dict[str, Any]) -> dict[str, str]:
    """Render every widget partial against the shared context.

    Each Jinja template gets the same context dict; the partials only
    read the variables they need. ``request`` is included because some
    base macros / url_for calls rely on it.
    """
    full_ctx = {"request": request, **context}
    return {key: templates.get_template(path).render(full_ctx) for key, path in _WIDGET_PARTIALS.items()}


def get_dashboard_snapshot(
    request: Request,
    db: Session,
    user: User,
    *,
    force: bool = False,
) -> dict[str, str]:
    """Return cached widget HTML map, recomputing only when the TTL expires.

    ``force=True`` bypasses the cache (tests; production relies on the TTL).
    """
    now = time.monotonic()
    cached = _cache["value"]
    if not force and cached is not None and now < _cache["expires_at"]:
        return dict(cached)

    templates: Jinja2Templates = request.app.state.templates
    context = build_dashboard_context(db, user)
    fresh = _render_snapshot(request, templates, context)
    _cache["value"] = fresh
    _cache["expires_at"] = now + _CACHE_TTL_SECONDS
    return dict(fresh)


def invalidate_cache() -> None:
    """Drop the cached snapshot so the next request recomputes from DB.

    Exposed for tests; production relies on the TTL.
    """
    _cache["value"] = None
    _cache["expires_at"] = 0.0
