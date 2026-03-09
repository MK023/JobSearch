"""CV routes."""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from ..audit.service import audit
from ..config import settings
from ..dependencies import CurrentUser, DbSession
from .service import get_latest_cv, save_cv

router = APIRouter(tags=["cv"])


@router.post("/cv", response_class=HTMLResponse)
def save_cv_route(
    request: Request,
    db: DbSession,
    user: CurrentUser,
    cv_text: str = Form(...),
    cv_name: str = Form(""),
):
    if len(cv_text) < 20:
        request.session["flash_error"] = "CV troppo corto (minimo 20 caratteri)"
        return RedirectResponse(url="/settings", status_code=303)
    if len(cv_text) > settings.max_cv_size:
        request.session["flash_error"] = f"CV troppo lungo (max {settings.max_cv_size} caratteri)"
        return RedirectResponse(url="/settings", status_code=303)

    save_cv(db, user.id, cv_text, cv_name)
    audit(db, request, "cv_save", f"name={cv_name}, len={len(cv_text)}")
    db.commit()
    request.session["flash_message"] = "CV salvato con successo!"
    return RedirectResponse(url="/settings", status_code=303)


@router.get("/cv/download")
def download_cv(
    request: Request,
    db: DbSession,
    user: CurrentUser,
):
    cv = get_latest_cv(db, user.id)
    if not cv:
        return RedirectResponse(url="/", status_code=303)
    audit(db, request, "cv_download", f"name={cv.name}")
    db.commit()
    filename = f"CV_{cv.name or 'unnamed'}.txt".replace(" ", "_")
    return PlainTextResponse(
        cv.raw_text,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
