"""Cover letter routes."""

import logging
from typing import cast
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from ..analysis.service import get_analysis_by_id
from ..audit.service import audit
from ..config import settings
from ..cv.service import get_latest_cv
from ..dashboard.service import add_spending, check_budget_available
from ..dependencies import Cache, CurrentUser, DbSession, validate_uuid
from ..rate_limit import limiter
from .service import build_docx, create_cover_letter, get_cover_letter_by_id

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cover_letter"])


@router.post("/cover-letter", response_class=HTMLResponse)
@limiter.limit(settings.rate_limit_analyze)
def generate_cover_letter_route(
    request: Request,
    db: DbSession,
    user: CurrentUser,
    cache: Cache,
    analysis_id: str = Form(...),
    language: str = Form("italiano"),
    model: str = Form("haiku"),
) -> Response:
    ALLOWED_LANGUAGES = {"italiano", "inglese", "francese", "tedesco", "spagnolo"}
    if language not in ALLOWED_LANGUAGES:
        language = "italiano"
    """Generate a cover letter via AI and redirect back to the analysis page."""
    safe_id = str(validate_uuid(analysis_id))
    analysis = get_analysis_by_id(db, safe_id)
    if not analysis:
        request.session["flash_error"] = "Analisi non trovata"
        return RedirectResponse(url="/history", status_code=303)

    cv = get_latest_cv(db, cast(UUID, user.id))
    if not cv:
        request.session["flash_error"] = "CV non trovato"
        return RedirectResponse(url=f"/analysis/{safe_id}", status_code=303)

    budget_ok, budget_msg = check_budget_available(db)
    if not budget_ok:
        request.session["flash_error"] = budget_msg
        return RedirectResponse(url=f"/analysis/{safe_id}", status_code=303)

    try:
        cl, result = create_cover_letter(db, analysis, cast(str, cv.raw_text), language, model, cache)
        add_spending(
            db,
            result.get("cost_usd", 0.0),
            result.get("tokens", {}).get("input", 0),
            result.get("tokens", {}).get("output", 0),
            is_analysis=False,
        )
        audit(db, request, "cover_letter", f"analysis={safe_id}, lang={language}")
        db.commit()
    except Exception as exc:
        db.rollback()
        audit(db, request, "cover_letter_error", str(exc))
        db.commit()
        logger.exception("Cover letter generation failed")
        request.session["flash_error"] = "Generazione cover letter fallita, riprova."
        return RedirectResponse(url=f"/analysis/{safe_id}", status_code=303)

    request.session["flash_message"] = f"Cover letter generata! ({language})"
    return RedirectResponse(url=f"/analysis/{safe_id}", status_code=303)


@router.get("/api/v1/cover-letter/{cover_letter_id}")
def get_cover_letter_text(
    cover_letter_id: str,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Return cover letter content as JSON (for clipboard copy)."""
    validate_uuid(cover_letter_id)
    cl = get_cover_letter_by_id(db, cover_letter_id)
    if not cl:
        return JSONResponse({"error": "Cover letter non trovata"}, status_code=404)
    return JSONResponse({"content": cl.content})


@router.get("/cover-letter/{cover_letter_id}/download")
def download_cover_letter(
    cover_letter_id: str,
    db: DbSession,
    user: CurrentUser,
) -> Response:
    """Download a cover letter as a formatted DOCX file."""
    validate_uuid(cover_letter_id)
    cl = get_cover_letter_by_id(db, cover_letter_id)
    if not cl:
        return Response("Cover letter non trovata", status_code=404)

    analysis = get_analysis_by_id(db, str(cl.analysis_id))
    if not analysis:
        return Response("Analisi collegata non trovata", status_code=404)

    buf, filename = build_docx(cl, analysis)

    # RFC 5987 encoding for non-ASCII filenames
    encoded_filename = quote(filename)

    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{encoded_filename}",
        },
    )
