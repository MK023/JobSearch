"""Dashboard and spending routes."""

from typing import Annotated

from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse
from sqlalchemy import func

from ..analysis.models import JobAnalysis
from ..audit.models import AuditLog
from ..batch.models import BatchItem
from ..dependencies import CurrentUser, DbSession
from .service import get_dashboard, get_spending, update_budget

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
    analyses_count = db.query(func.count(JobAnalysis.id)).scalar() or 0
    batch_items_count = db.query(func.count(BatchItem.id)).scalar() or 0
    audit_logs_count = db.query(func.count(AuditLog.id)).scalar() or 0

    # Rough estimate: ~50KB per analysis (includes job_description + full_response),
    # ~1KB per audit log, ~5KB per batch item (includes job_description)
    estimated_size_mb = round(
        (analyses_count * 50 + batch_items_count * 5 + audit_logs_count * 1) / 1024,
        1,
    )

    return JSONResponse(
        {
            "analyses_count": analyses_count,
            "batch_items_count": batch_items_count,
            "audit_logs_count": audit_logs_count,
            "estimated_size_mb": estimated_size_mb,
        }
    )
