"""/analytics page (HTML) + POST /analytics/run (JSON API v1)."""

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from ..audit.service import audit
from ..dependencies import CurrentUser, DbSession
from ..rate_limit import limiter
from .service import UNLOCK_THRESHOLD, get_latest_runs, get_lock_state, run_analytics

# HTML page router — registered at root level (no prefix)
page_router = APIRouter(tags=["analytics-page"])

# JSON API router — registered under /api/v1
api_router = APIRouter(tags=["analytics-api"])


@page_router.get("/analytics", response_class=HTMLResponse)
def analytics_page(
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> Response:
    """Render the analytics page with lock state + latest run snapshot."""
    templates = request.app.state.templates
    lock = get_lock_state(db)
    runs = get_latest_runs(db, limit=5)
    latest = runs[0] if runs else None
    history = runs[1:] if len(runs) > 1 else []

    from ..pages import _base_ctx, _flash

    flash = _flash(request)
    return templates.TemplateResponse(  # type: ignore[no-any-return]
        request,
        "analytics.html",
        {
            **_base_ctx(db, user, "analytics"),
            "lock": lock,
            "threshold": UNLOCK_THRESHOLD,
            "latest_run": latest,
            "run_history": history,
            "error": flash["error"],
            "message": flash["message"],
        },
    )


@api_router.post("/analytics/run")
@limiter.limit("3/hour")
def trigger_run(
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Trigger an analytics run. Respects lock state."""
    lock = get_lock_state(db)
    if lock["locked"]:
        return JSONResponse(
            {
                "ok": False,
                "reason": "locked",
                "new_since_last": lock["new_since_last"],
                "threshold": UNLOCK_THRESHOLD,
            },
            status_code=409,
        )

    run = run_analytics(db, cast(UUID, user.id), triggered_by="manual")
    audit(db, request, "analytics_run", f"run_id={run.id}")
    db.commit()

    return JSONResponse(
        {
            "ok": True,
            "run_id": str(run.id),
            "analyses_count": run.analyses_count,
        }
    )
