"""Authentication routes."""

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from ..audit.service import audit
from ..dependencies import DbSession
from ..rate_limit import limiter
from .service import authenticate_user

router = APIRouter(tags=["auth"])


def _get_templates(request: Request) -> Jinja2Templates:
    return cast(Jinja2Templates, request.app.state.templates)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> Response:
    templates = _get_templates(request)
    if request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "login.html")  # type: ignore[return-value]


@router.post("/login")
@limiter.limit("5/minute")
def login(
    request: Request,
    db: DbSession,
    email: str = Form(...),
    password: str = Form(...),
) -> Response:
    templates = _get_templates(request)
    user = authenticate_user(db, email, password)
    if not user:
        audit(db, request, "login_failed", f"email={email}")
        db.commit()
        return templates.TemplateResponse(  # type: ignore[return-value]
            request,
            "login.html",
            {"error": "Invalid credentials"},
            status_code=401,
        )
    request.session["user_id"] = str(user.id)
    audit(db, request, "login", f"email={email}", user_id=cast(UUID, user.id))
    db.commit()
    return RedirectResponse(url="/", status_code=303)


@router.post("/logout")
def logout(request: Request, db: DbSession) -> Response:
    audit(db, request, "logout")
    db.commit()
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
