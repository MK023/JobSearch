"""Analysis HTML routes — SSR Jinja2 per ``/analyze``, ``/analysis/{id}``.

Form ``/analyze`` accetta il job description + URL e instrada verso
``analyze_and_charge``: URL dedup (stesso URL già visto → mostra
cached), content_hash dedup (testo equivalente → riusa analisi), budget
gate (rifiuta se Anthropic budget exhausted), audit log.

``/analysis/{id}`` mostra il detail con risultati AI, contacts,
cover_letters ordinate newest-first, interview rounds, status transition
buttons. Le route API (PATCH status, DELETE) vivono in ``api_routes.py``.
"""

from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ..audit.service import audit
from ..config import settings
from ..cv.service import get_latest_cv
from ..dashboard.service import check_budget_available
from ..dependencies import Cache, CurrentUser, DbSession
from ..integrations.anthropic_client import MODELS, content_hash
from ..rate_limit import limiter
from .models import AnalysisSource
from .service import (
    analyze_and_charge,
    find_by_company,
    find_by_url,
    find_existing_analysis,
    get_analysis_by_id,
    rebuild_result,
)

router = APIRouter(tags=["analysis"])

_ANALYZE_PATH = "/analyze"


@router.post(_ANALYZE_PATH, response_class=HTMLResponse)
@limiter.limit(settings.rate_limit_analyze)
def analyze(
    request: Request,
    db: DbSession,
    user: CurrentUser,
    cache: Cache,
    job_description: Annotated[str, Form()],
    job_url: Annotated[str, Form()] = "",
    model: Annotated[str, Form()] = "haiku",
) -> Response:
    """Submit a job description for AI analysis against the user's CV."""
    cv = get_latest_cv(db, cast(UUID, user.id))

    if not cv:
        request.session["flash_error"] = "Salva prima il tuo CV!"
        return RedirectResponse(url=_ANALYZE_PATH, status_code=303)

    if len(job_description) > settings.max_job_desc_size:
        request.session["flash_error"] = f"Descrizione troppo lunga (max {settings.max_job_desc_size} caratteri)"
        return RedirectResponse(url=_ANALYZE_PATH, status_code=303)

    budget_ok, budget_msg = check_budget_available(db)
    if not budget_ok:
        request.session["flash_error"] = budget_msg
        return RedirectResponse(url=_ANALYZE_PATH, status_code=303)

    # URL dedup: same job posting pasted again (even with different JD text).
    if job_url:
        existing_url = find_by_url(db, job_url)
        if existing_url:
            audit(db, request, "analyze_cache_url", f"id={existing_url.id}")
            request.session["flash_message"] = (
                f"URL già analizzato il {cast(datetime, existing_url.created_at).strftime('%d/%m/%Y %H:%M')} - mostro il risultato salvato"
            )
            return RedirectResponse(url=f"/analysis/{existing_url.id}", status_code=303)

    ch = content_hash(cast(str, cv.raw_text), job_description)
    model_id = MODELS.get(model, MODELS["haiku"])
    existing = find_existing_analysis(db, ch, model_id)

    if existing:
        audit(db, request, "analyze_cache", f"id={existing.id}")
        request.session["flash_message"] = (
            f"Analisi gia' eseguita il {cast(datetime, existing.created_at).strftime('%d/%m/%Y %H:%M')} - mostro il risultato salvato"
        )
        return RedirectResponse(url=f"/analysis/{existing.id}", status_code=303)

    try:
        analysis, _result = analyze_and_charge(
            db,
            cast(str, cv.raw_text),
            cast(UUID, cv.id),
            job_description,
            job_url,
            model,
            cache,
            user_id=cast(UUID, user.id),
            source=AnalysisSource.COWORK.value,  # HTML form from /analyze = cowork paste flow
        )
        audit(db, request, "analyze", f"id={analysis.id}, company={analysis.company}, score={analysis.score}")
        db.commit()
    except Exception as exc:
        db.rollback()
        audit(db, request, "analyze_error", str(exc))
        db.commit()
        request.session["flash_error"] = "Analisi AI fallita, riprova più tardi."
        return RedirectResponse(url=_ANALYZE_PATH, status_code=303)

    return RedirectResponse(url=f"/analysis/{analysis.id}", status_code=303)


@router.get("/analysis/{analysis_id}", response_class=HTMLResponse)
def view_analysis(
    request: Request,
    analysis_id: str,
    db: DbSession,
    user: CurrentUser,
) -> Response:
    """Render the detail page for a single analysis."""
    from ..contacts.service import get_contacts_for_analysis
    from ..interview.service import get_interview_by_analysis

    analysis = get_analysis_by_id(db, analysis_id, user_id=cast(UUID, user.id))
    if not analysis:
        return RedirectResponse(url="/history", status_code=303)

    result = rebuild_result(analysis)
    interview = get_interview_by_analysis(db, cast(UUID, analysis.id))
    same_company_analyses = find_by_company(db, cast(str, analysis.company), exclude_id=cast(UUID, analysis.id))
    # Sort newest-first so a fresh bilingual generation (italiano + english)
    # appears in the correct order at the top of the page.
    cover_letters = sorted(
        analysis.cover_letters or [],
        key=lambda c: cast(datetime, c.created_at),
        reverse=True,
    )
    cover_letter = cover_letters[0] if cover_letters else None  # back-compat alias
    contacts = get_contacts_for_analysis(db, str(analysis.id))

    error = request.session.pop("flash_error", None)
    message = request.session.pop("flash_message", None)

    # Sidebar context — use _base_ctx so every badge (Storico pending,
    # Agenda todos, Analytics unlock, Notifiche) keeps showing on the
    # analysis detail page. The previous hand-rolled dict only passed
    # notification + interview counts, so the other badges disappeared
    # as soon as the user opened an analysis.
    from ..pages import _base_ctx

    templates = request.app.state.templates
    return templates.TemplateResponse(  # type: ignore[no-any-return]
        request,
        "analysis_detail.html",
        {
            **_base_ctx(db, user, "history"),
            "current": analysis,
            "result": result,
            "interview": interview,
            "cover_letter": cover_letter,
            "cover_letters": cover_letters,
            "contacts": contacts,
            "same_company_analyses": same_company_analyses,
            "error": error,
            "message": message,
        },
    )
