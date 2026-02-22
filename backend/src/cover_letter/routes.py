"""Cover letter routes."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from ..analysis.routes import _render_page
from ..analysis.service import get_analysis_by_id, rebuild_result
from ..audit.service import audit
from ..auth.models import User
from ..cv.service import get_latest_cv
from ..dashboard.service import add_spending
from ..database import get_db
from ..dependencies import get_cache, get_current_user
from ..integrations.cache import CacheService
from .service import build_docx, create_cover_letter, get_cover_letter_by_id

router = APIRouter(tags=["cover_letter"])


@router.post("/cover-letter", response_class=HTMLResponse)
def generate_cover_letter_route(
    request: Request,
    analysis_id: str = Form(...),
    language: str = Form("italiano"),
    model: str = Form("haiku"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    cache: CacheService = Depends(get_cache),
):
    analysis = get_analysis_by_id(db, analysis_id)
    if not analysis:
        return _render_page(request, db, user, error="Analisi non trovata")

    cv = get_latest_cv(db, user.id)
    if not cv:
        return _render_page(request, db, user, error="CV non trovato")

    try:
        cl, result = create_cover_letter(db, analysis, cv.raw_text, language, model, cache)
        add_spending(
            db,
            result.get("cost_usd", 0.0),
            result.get("tokens", {}).get("input", 0),
            result.get("tokens", {}).get("output", 0),
            is_analysis=False,
        )
        audit(db, request, "cover_letter", f"analysis={analysis_id}, lang={language}")
        db.commit()
    except Exception as exc:
        audit(db, request, "cover_letter_error", str(exc))
        db.commit()
        return _render_page(request, db, user, error=f"Generazione cover letter fallita: {exc}")

    analysis_result = rebuild_result(analysis)
    return _render_page(
        request,
        db,
        user,
        current=analysis,
        result=analysis_result,
        cover_letter=cl,
        cover_letter_result=result,
        message=f"Cover letter generata! ({language})",
    )


@router.get("/cover-letter/{cover_letter_id}/download")
def download_cover_letter(
    cover_letter_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Download a cover letter as a formatted DOCX file."""
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
