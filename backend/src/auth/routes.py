"""Authentication routes — login / logout SSR + session management.

Single-user app: l'unica utente è ``ensure_admin_user`` (seedato a
startup dalle env ``ADMIN_EMAIL`` / ``ADMIN_PASSWORD``). Login form
POST verifica bcrypt hash, gestisce lockout brute-force (5 tentativi
falliti = 30 min di lockout in ``users.locked_until``), audit logga
ogni success/failure.

Session backend: Starlette ``SessionMiddleware`` con cookie firmato
(``SECRET_KEY``). Lo storage è server-side (no JWT, no auth provider)
per minimizzare la attack surface su un perimetro single-user.
"""

from typing import Annotated, cast
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
    """Retrieve the Jinja2 templates instance from app state."""
    return cast(Jinja2Templates, request.app.state.templates)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> Response:
    """Render the login page, or redirect to home if already authenticated."""
    templates = _get_templates(request)
    if request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "login.html")


@router.post("/login")
@limiter.limit("5/minute")
def login(
    request: Request,
    db: DbSession,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> Response:
    """Authenticate user credentials and create a session."""
    templates = _get_templates(request)
    user = authenticate_user(db, email, password)
    if not user:
        audit(db, request, "login_failed", f"email={email}")
        db.commit()
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid credentials"},
            status_code=401,
        )
    # Session regeneration: clear old session before setting new one
    # to prevent session fixation attacks.
    request.session.clear()
    request.session["user_id"] = str(user.id)
    audit(db, request, "login", f"email={email}", user_id=cast(UUID, user.id))
    db.commit()
    return RedirectResponse(url="/", status_code=303)


@router.post("/logout")
def logout(request: Request, db: DbSession) -> Response:
    """Clear user session and redirect to login page."""
    audit(db, request, "logout")
    db.commit()
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
