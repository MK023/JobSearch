"""Authentication routes."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..audit.service import audit
from ..database import get_db
from .service import authenticate_user

router = APIRouter(tags=["auth"])


def _get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    templates = _get_templates(request)
    if request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    templates = _get_templates(request)
    user = authenticate_user(db, email, password)
    if not user:
        audit(db, request, "login_failed", f"email={email}")
        db.commit()
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid credentials"},
            status_code=401,
        )
    request.session["user_id"] = str(user.id)
    audit(db, request, "login", f"email={email}", user_id=user.id)
    db.commit()
    return RedirectResponse(url="/", status_code=303)


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    audit(db, request, "logout")
    db.commit()
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
