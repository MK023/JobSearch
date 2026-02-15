"""Dashboard and spending routes."""

from fastapi import APIRouter, Depends, Form
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..auth.models import User
from ..database import get_db
from ..dependencies import get_current_user
from .service import get_dashboard, get_spending, update_budget

router = APIRouter(tags=["dashboard"])


@router.get("/spending")
def spending_api(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return JSONResponse(get_spending(db))


@router.put("/spending/budget")
def set_budget(
    budget: float = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    new_budget = update_budget(db, budget)
    db.commit()
    return JSONResponse({"ok": True, "budget": new_budget})


@router.get("/dashboard")
def dashboard_api(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return JSONResponse(get_dashboard(db))
