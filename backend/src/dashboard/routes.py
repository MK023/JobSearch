"""Dashboard and spending routes."""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse

from ..dependencies import CurrentUser, DbSession
from ..rate_limit import limiter
from .service import get_dashboard, get_db_usage, get_spending, update_budget

router = APIRouter(tags=["dashboard"])


@router.get("/spending")
def spending_api(
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Return current spending totals and budget info."""
    return JSONResponse(get_spending(db))


@router.put("/spending/budget")
def set_budget(
    db: DbSession,
    user: CurrentUser,
    budget: Annotated[float, Form()],
) -> JSONResponse:
    """Set the Anthropic API spending budget (0-1000 USD)."""
    if budget < 0 or budget > 1000:
        return JSONResponse({"error": "Budget deve essere tra 0 e 1000 USD"}, status_code=400)
    new_budget = update_budget(db, budget)
    db.commit()
    return JSONResponse({"ok": True, "budget": new_budget})


@router.get("/dashboard")
def dashboard_api(
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Return dashboard statistics (counts, avg score, top match)."""
    return JSONResponse(get_dashboard(db))


@router.get("/db-usage")
def db_usage(
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Return DB row counts and estimated size to monitor the 1GB free-tier limit."""
    return JSONResponse(get_db_usage(db))


@router.post("/backup")
@limiter.limit("2/hour")
def create_backup_endpoint(
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Create a DB backup on R2. Rate-limited to 2/hour."""
    from ..integrations.backup import create_backup

    try:
        result = create_backup(db)
        return JSONResponse({"ok": True, **result})
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    except Exception:
        return JSONResponse({"error": "Backup failed"}, status_code=500)


@router.get("/backups")
def list_backups_endpoint(
    user: CurrentUser,
) -> JSONResponse:
    """List available backups on R2."""
    from ..integrations.backup import list_backups

    return JSONResponse(list_backups())
