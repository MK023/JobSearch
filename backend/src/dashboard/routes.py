"""Dashboard and spending routes."""

from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse

from ..dependencies import CurrentUser, DbSession
from .service import get_dashboard, get_spending, update_budget

router = APIRouter(tags=["dashboard"])


@router.get("/spending")
def spending_api(
    db: DbSession,
    user: CurrentUser,
):
    return JSONResponse(get_spending(db))


@router.put("/spending/budget")
def set_budget(
    db: DbSession,
    user: CurrentUser,
    budget: float = Form(...),
):
    new_budget = update_budget(db, budget)
    db.commit()
    return JSONResponse({"ok": True, "budget": new_budget})


@router.get("/dashboard")
def dashboard_api(
    db: DbSession,
    user: CurrentUser,
):
    return JSONResponse(get_dashboard(db))
