"""CV routes."""

import re
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response

from ..audit.service import audit
from ..config import settings
from ..dependencies import CurrentUser, DbSession
from .service import get_latest_cv, save_cv
from .text_extract import extract_text

router = APIRouter(tags=["cv"])

_SETTINGS_URL = "/settings"


@router.post("/cv", response_class=HTMLResponse)
async def save_cv_route(
    request: Request,
    db: DbSession,
    user: CurrentUser,
    cv_text: Annotated[str, Form()] = "",
    cv_name: Annotated[str, Form()] = "",
    cv_file: Annotated[UploadFile | None, File()] = None,
) -> Response:
    """Validate and save the user's CV text or uploaded file."""
    # If file uploaded, extract text from it
    if cv_file and cv_file.filename and cv_file.size:
        try:
            file_bytes = await cv_file.read()
            cv_text = extract_text(file_bytes, cv_file.filename)
        except ValueError as exc:
            request.session["flash_error"] = str(exc)
            return RedirectResponse(url=_SETTINGS_URL, status_code=303)

    if len(cv_text) < 20:
        request.session["flash_error"] = "CV troppo corto (minimo 20 caratteri)"
        return RedirectResponse(url=_SETTINGS_URL, status_code=303)
    if len(cv_text) > settings.max_cv_size:
        request.session["flash_error"] = f"CV troppo lungo (max {settings.max_cv_size} caratteri)"
        return RedirectResponse(url=_SETTINGS_URL, status_code=303)

    save_cv(db, cast(UUID, user.id), cv_text, cv_name)
    audit(db, request, "cv_save", f"name={cv_name}, len={len(cv_text)}")
    db.commit()
    request.session["flash_message"] = "CV salvato con successo!"
    return RedirectResponse(url=_SETTINGS_URL, status_code=303)


@router.get("/cv/download")
def download_cv(
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> Response:
    """Download the user's latest CV as a plain text file."""
    cv = get_latest_cv(db, cast(UUID, user.id))
    if not cv:
        return RedirectResponse(url="/", status_code=303)
    audit(db, request, "cv_download", f"name={cv.name}")
    db.commit()
    safe_name = re.sub(r"[^a-zA-Z0-9\s\-_]", "", str(cv.name or "unnamed"))[:50]
    filename = f"CV_{safe_name}.txt".replace(" ", "_")
    return PlainTextResponse(
        cv.raw_text,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
