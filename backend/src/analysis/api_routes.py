"""Analysis JSON API routes (status changes, deletion, AJAX analysis)."""

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ..audit.service import audit
from ..config import settings
from ..cover_letter.models import CoverLetter
from ..cv.service import get_latest_cv
from ..dashboard.service import add_spending, check_budget_available, remove_spending
from ..dependencies import Cache, CurrentUser, DbSession, validate_uuid
from ..integrations.anthropic_client import MODELS, content_hash
from ..rate_limit import limiter
from .models import AnalysisStatus, JobAnalysis
from .schemas import AnalysisImportRequest, AnalyzeRequest
from .service import find_existing_analysis, get_analysis_by_id, run_analysis, update_status

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analysis-api"])


@router.post("/analyze")
@limiter.limit(settings.rate_limit_analyze)
def analyze_api(
    request: Request,
    body: AnalyzeRequest,
    db: DbSession,
    user: CurrentUser,
    cache: Cache,
) -> JSONResponse:
    """Run analysis via JSON API (AJAX). Returns redirect URL."""
    cv = get_latest_cv(db, cast(UUID, user.id))
    if not cv:
        return JSONResponse({"error": "Salva prima il tuo CV!"}, status_code=400)

    if len(body.job_description) > settings.max_job_desc_size:
        return JSONResponse(
            {"error": f"Descrizione troppo lunga (max {settings.max_job_desc_size} caratteri)"},
            status_code=400,
        )

    budget_ok, budget_msg = check_budget_available(db)
    if not budget_ok:
        return JSONResponse({"error": budget_msg}, status_code=400)

    ch = content_hash(cast(str, cv.raw_text), body.job_description)
    model_id = MODELS.get(body.model, MODELS["haiku"])
    existing = find_existing_analysis(db, ch, model_id)

    if existing:
        audit(db, request, "analyze_cache", f"id={existing.id}")
        db.commit()
        return JSONResponse({"ok": True, "redirect": f"/analysis/{existing.id}", "cached": True})

    try:
        analysis, result = run_analysis(
            db, cast(str, cv.raw_text), cast(UUID, cv.id), body.job_description, body.job_url, body.model, cache
        )
        add_spending(
            db,
            result.get("cost_usd", 0.0),
            result.get("tokens", {}).get("input", 0),
            result.get("tokens", {}).get("output", 0),
        )
        audit(db, request, "analyze", f"id={analysis.id}, company={analysis.company}, score={analysis.score}")
        db.commit()
    except Exception as exc:
        db.rollback()
        audit(db, request, "analyze_error", str(exc))
        db.commit()
        logger.exception("AI analysis failed")
        return JSONResponse({"error": "Analisi AI non disponibile, riprova."}, status_code=500)

    return JSONResponse({"ok": True, "redirect": f"/analysis/{analysis.id}"})


@router.get("/analysis/latest")
def latest_analysis(
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Return the most recent analysis for the current user (background completion polling)."""
    from ..cv.models import CVProfile
    from .models import JobAnalysis

    user_cv_ids = db.query(CVProfile.id).filter(CVProfile.user_id == user.id)
    analysis = (
        db.query(JobAnalysis).filter(JobAnalysis.cv_id.in_(user_cv_ids)).order_by(JobAnalysis.created_at.desc()).first()
    )
    if not analysis:
        return JSONResponse({"id": None})
    return JSONResponse(
        {
            "id": str(analysis.id),
            "company": analysis.company,
            "role": analysis.role,
            "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
        }
    )


@router.post("/status/{analysis_id}/{new_status}")
def change_status(
    request: Request,
    analysis_id: str,
    new_status: str,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Update the tracking status of an analysis."""
    validate_uuid(analysis_id)
    try:
        status_enum = AnalysisStatus(new_status)
    except ValueError:
        return JSONResponse({"error": "invalid status"}, status_code=400)

    analysis = get_analysis_by_id(db, analysis_id, user_id=cast(UUID, user.id))
    if not analysis:
        return JSONResponse({"error": "not found"}, status_code=404)

    update_status(db, analysis, status_enum)
    audit(db, request, "status_change", f"id={analysis_id}, status={new_status}")
    db.commit()
    return JSONResponse({"ok": True, "status": new_status})


@router.delete("/analysis/{analysis_id}")
def delete_analysis(
    request: Request,
    analysis_id: str,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Delete an analysis and reverse its spending totals."""
    validate_uuid(analysis_id)
    analysis = get_analysis_by_id(db, analysis_id, user_id=cast(UUID, user.id))
    if not analysis:
        return JSONResponse({"error": "Analysis not found"}, status_code=404)

    today = date.today()

    cover_letters = db.query(CoverLetter).filter(CoverLetter.analysis_id == analysis.id).all()
    for cl in cover_letters:
        cl_today = cl.created_at and cl.created_at.date() == today
        remove_spending(
            db,
            float(cl.cost_usd or 0),
            int(cl.tokens_input or 0),
            int(cl.tokens_output or 0),
            is_analysis=False,
            created_today=bool(cl_today),
        )

    a_today = analysis.created_at and analysis.created_at.date() == today
    remove_spending(
        db,
        float(analysis.cost_usd or 0),
        int(analysis.tokens_input or 0),
        int(analysis.tokens_output or 0),
        is_analysis=True,
        created_today=bool(a_today),
    )

    audit(db, request, "delete_analysis", f"id={analysis_id}, {analysis.role} @ {analysis.company}")
    db.delete(analysis)
    db.commit()

    return JSONResponse({"ok": True})


@router.post("/analysis/import")
@limiter.limit(settings.rate_limit_analyze)
def import_analysis(
    request: Request,
    body: AnalysisImportRequest,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Import a pre-computed analysis from the MCP server and persist it."""
    cv = get_latest_cv(db, cast(UUID, user.id))
    if not cv:
        return JSONResponse({"error": "No CV found. Upload a CV first."}, status_code=400)

    # Dedup check
    existing = find_existing_analysis(db, body.content_hash, body.model_used)
    if existing:
        audit(db, request, "import_analysis_dedup", f"id={existing.id}")
        db.commit()
        return JSONResponse({"ok": True, "analysis_id": str(existing.id), "duplicate": True})

    analysis = JobAnalysis(
        cv_id=cv.id,
        job_description=body.job_description,
        job_url=body.job_url,
        content_hash=body.content_hash,
        job_summary=body.job_summary,
        company=body.company,
        role=body.role,
        location=body.location,
        work_mode=body.work_mode,
        salary_info=body.salary_info,
        score=body.score,
        recommendation=body.recommendation,
        strengths=body.strengths,
        gaps=body.gaps,
        interview_scripts=body.interview_scripts,
        advice=body.advice,
        company_reputation=body.company_reputation,
        full_response=body.full_response,
        model_used=body.model_used,
        tokens_input=body.tokens_input,
        tokens_output=body.tokens_output,
        cost_usd=body.cost_usd,
    )
    db.add(analysis)
    db.flush()

    add_spending(db, body.cost_usd, body.tokens_input, body.tokens_output)
    audit(db, request, "import_analysis", f"id={analysis.id}, company={body.company}, score={body.score}")
    db.commit()

    return JSONResponse({"ok": True, "analysis_id": str(analysis.id), "duplicate": False})


@router.get("/analysis/check-dedup")
def check_dedup(
    content_hash: Annotated[str, Query(max_length=128, pattern=r"^[a-f0-9]+$")],
    model_id: Annotated[str, Query(max_length=100)],
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Check if an analysis with the given content_hash and model_id already exists."""
    existing = find_existing_analysis(db, content_hash, model_id)
    if existing:
        return JSONResponse({"exists": True, "analysis_id": str(existing.id)})
    return JSONResponse({"exists": False})


@router.delete("/analysis/cleanup")
@limiter.limit(settings.rate_limit_analyze)
def cleanup_analyses(
    request: Request,
    db: DbSession,
    user: CurrentUser,
    days: Annotated[int, Query(ge=1, le=365, description="Delete analyses older than N days")] = 90,
    max_score: Annotated[int, Query(ge=0, le=100, description="Only delete analyses with score <= this")] = 40,
    dry_run: Annotated[bool, Query(description="If True, return count without deleting")] = True,
) -> JSONResponse:
    """Delete old low-score analyses to free DB space (1GB free-tier limit).

    Only deletes analyses with status=PENDING (da_valutare).
    Analyses marked as applied/interview/rejected are preserved.
    """
    cutoff = datetime.now(UTC) - timedelta(days=days)

    # Scope to the authenticated user's CVs only — cleanup must never
    # cross user boundaries.
    from ..cv.models import CVProfile

    user_cv_ids = db.query(CVProfile.id).filter(CVProfile.user_id == user.id)

    candidates = (
        db.query(JobAnalysis)
        .filter(
            JobAnalysis.cv_id.in_(user_cv_ids),
            JobAnalysis.score <= max_score,
            JobAnalysis.created_at < cutoff,
            JobAnalysis.status == AnalysisStatus.PENDING,
        )
        .all()
    )

    count = len(candidates)

    if dry_run:
        audit(db, request, "cleanup_dry_run", f"would_delete={count}, days={days}, max_score={max_score}")
        db.commit()
        return JSONResponse({"ok": True, "deleted": count, "dry_run": True})

    today = date.today()
    for analysis in candidates:
        # Reverse spending for associated cover letters
        cover_letters = db.query(CoverLetter).filter(CoverLetter.analysis_id == analysis.id).all()
        for cl in cover_letters:
            cl_today = cl.created_at and cl.created_at.date() == today
            remove_spending(
                db,
                float(cl.cost_usd or 0),
                int(cl.tokens_input or 0),
                int(cl.tokens_output or 0),
                is_analysis=False,
                created_today=bool(cl_today),
            )

        # Reverse spending for the analysis itself
        a_today = analysis.created_at and analysis.created_at.date() == today
        remove_spending(
            db,
            float(analysis.cost_usd or 0),
            int(analysis.tokens_input or 0),
            int(analysis.tokens_output or 0),
            is_analysis=True,
            created_today=bool(a_today),
        )
        db.delete(analysis)

    sample_ids = [str(a.id) for a in candidates[:5]]
    audit(db, request, "cleanup", f"deleted={count}, days={days}, max_score={max_score}, sample={sample_ids}")
    db.commit()

    return JSONResponse({"ok": True, "deleted": count, "dry_run": False})


@router.get("/analysis/bulk-reject-preview")
@limiter.limit(settings.rate_limit_default)
def bulk_reject_preview(
    request: Request,
    db: DbSession,
    user: CurrentUser,
    days: Annotated[int, Query(ge=1, le=365)] = 14,
    max_score: Annotated[int, Query(ge=0, le=100)] = 60,
) -> JSONResponse:
    """Read-only count of da_valutare analyses that would be bulk-rejected.

    Filters: status=PENDING, created_at older than `days`, score <= `max_score`,
    scoped to the authenticated user's CVs.
    """
    from ..cv.models import CVProfile

    cutoff = datetime.now(UTC) - timedelta(days=days)
    user_cv_ids = db.query(CVProfile.id).filter(CVProfile.user_id == user.id)
    count = (
        db.query(JobAnalysis)
        .filter(
            JobAnalysis.cv_id.in_(user_cv_ids),
            JobAnalysis.score <= max_score,
            JobAnalysis.created_at < cutoff,
            JobAnalysis.status == AnalysisStatus.PENDING,
        )
        .count()
    )
    return JSONResponse({"count": count, "days": days, "max_score": max_score})


@router.post("/analysis/bulk-reject")
@limiter.limit(settings.rate_limit_analyze)
def bulk_reject(
    request: Request,
    db: DbSession,
    user: CurrentUser,
    days: Annotated[int, Query(ge=1, le=365)] = 14,
    max_score: Annotated[int, Query(ge=0, le=100)] = 60,
) -> JSONResponse:
    """Mark all matching da_valutare analyses as scartato in one transaction.

    Preserves analyses already marked applied/interview/rejected. Spending is
    NOT reversed — the analysis row is kept; only the tracking status changes.
    """
    from ..cv.models import CVProfile

    cutoff = datetime.now(UTC) - timedelta(days=days)
    user_cv_ids = db.query(CVProfile.id).filter(CVProfile.user_id == user.id)
    candidates = (
        db.query(JobAnalysis)
        .filter(
            JobAnalysis.cv_id.in_(user_cv_ids),
            JobAnalysis.score <= max_score,
            JobAnalysis.created_at < cutoff,
            JobAnalysis.status == AnalysisStatus.PENDING,
        )
        .all()
    )
    count = len(candidates)
    for analysis in candidates:
        analysis.status = AnalysisStatus.REJECTED.value  # type: ignore[assignment]
    sample_ids = [str(a.id) for a in candidates[:5]]
    audit(db, request, "bulk_reject", f"rejected={count}, days={days}, max_score={max_score}, sample={sample_ids}")
    db.commit()
    return JSONResponse({"ok": True, "rejected": count})


@router.get("/analysis/cleanup-preview")
@limiter.limit(settings.rate_limit_default)
def cleanup_preview(
    request: Request,
    db: DbSession,
    user: CurrentUser,
    days: Annotated[int, Query(ge=1, le=365)] = 90,
    max_score: Annotated[int, Query(ge=0, le=100)] = 40,
) -> JSONResponse:
    """Read-only count of analyses that would be deleted by /analysis/cleanup.

    Same filters as the DELETE endpoint, scoped to the authenticated user's
    CVs. No audit log (called from the UI on every parameter change).
    """
    from ..cv.models import CVProfile

    cutoff = datetime.now(UTC) - timedelta(days=days)
    user_cv_ids = db.query(CVProfile.id).filter(CVProfile.user_id == user.id)
    count = (
        db.query(JobAnalysis)
        .filter(
            JobAnalysis.cv_id.in_(user_cv_ids),
            JobAnalysis.score <= max_score,
            JobAnalysis.created_at < cutoff,
            JobAnalysis.status == AnalysisStatus.PENDING,
        )
        .count()
    )

    return JSONResponse({"count": count, "days": days, "max_score": max_score})
