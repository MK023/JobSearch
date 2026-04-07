"""Read-only API routes for MCP and external consumers."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from .analysis.models import JobAnalysis
from .analysis.service import (
    get_analysis_by_id,
    get_candidature,
    get_candidature_by_date_range,
    get_stale_candidature,
    get_top_candidature,
    rebuild_result,
    search_candidature,
)
from .contacts.service import search_all_contacts
from .cover_letter.models import CoverLetter
from .dashboard.service import get_dashboard, get_followup_alerts, get_spending
from .dependencies import CurrentUser, DbSession, validate_uuid
from .interview.service import get_upcoming_interviews

router = APIRouter(tags=["read-api"])


def _analysis_summary(a: JobAnalysis) -> dict[str, Any]:
    """Compact representation of an analysis for list endpoints."""
    return {
        "id": str(a.id),
        "company": a.company,
        "role": a.role,
        "score": a.score,
        "status": a.status or None,
        "location": a.location,
        "work_mode": a.work_mode,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "applied_at": a.applied_at.isoformat() if a.applied_at else None,
        "followed_up": a.followed_up,
    }


@router.get("/candidature")
def list_candidature(
    db: DbSession,
    user: CurrentUser,
    status: str | None = Query(None, description="Filter by status: da_valutare, candidato, colloquio, scartato"),
    limit: int = Query(50, ge=1, le=100),
) -> JSONResponse:
    """List candidature with optional status filter."""
    analyses = get_candidature(db, status=status, limit=limit)
    return JSONResponse({"candidature": [_analysis_summary(a) for a in analyses]})


@router.get("/candidature/search")
def candidature_search(
    db: DbSession,
    user: CurrentUser,
    q: str = Query(..., min_length=1, max_length=200, description="Search by company or role"),
    limit: int = Query(20, ge=1, le=50),
) -> JSONResponse:
    """Search candidature by company or role."""
    analyses = search_candidature(db, query=q, limit=limit)
    return JSONResponse({"candidature": [_analysis_summary(a) for a in analyses]})


@router.get("/candidature/top")
def top_candidature(
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(10, ge=1, le=50),
) -> JSONResponse:
    """Get top-scored candidature (excluding rejected)."""
    analyses = get_top_candidature(db, limit=limit)
    return JSONResponse({"candidature": [_analysis_summary(a) for a in analyses]})


@router.get("/candidature/date-range")
def candidature_by_date_range(
    db: DbSession,
    user: CurrentUser,
    date_from: str = Query(..., description="Start date (YYYY-MM-DD)"),
    date_to: str = Query(..., description="End date (YYYY-MM-DD)"),
) -> JSONResponse:
    """Get candidature within a date range."""
    try:
        dt_from = datetime.fromisoformat(date_from)
        dt_to = datetime.fromisoformat(date_to + "T23:59:59")
    except ValueError:
        return JSONResponse({"error": "Invalid date format. Use YYYY-MM-DD"}, status_code=400)

    analyses = get_candidature_by_date_range(db, dt_from, dt_to)
    return JSONResponse({"candidature": [_analysis_summary(a) for a in analyses]})


@router.get("/candidature/stale")
def stale_candidature(
    db: DbSession,
    user: CurrentUser,
    days: int = Query(7, ge=1, le=90, description="Days without updates"),
) -> JSONResponse:
    """Get candidature that haven't been updated in N days."""
    analyses = get_stale_candidature(db, days=days)
    return JSONResponse({"candidature": [_analysis_summary(a) for a in analyses]})


@router.get("/candidature/{analysis_id}")
def candidature_detail(
    analysis_id: str,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Get full detail for a single candidature."""
    validate_uuid(analysis_id)
    analysis = get_analysis_by_id(db, analysis_id)
    if not analysis:
        return JSONResponse({"error": "Analysis not found"}, status_code=404)

    result = rebuild_result(analysis)
    result["id"] = str(analysis.id)
    result["status"] = analysis.status or None
    result["created_at"] = analysis.created_at.isoformat() if analysis.created_at else None
    result["applied_at"] = analysis.applied_at.isoformat() if analysis.applied_at else None
    result["followed_up"] = analysis.followed_up
    result["job_url"] = analysis.job_url
    return JSONResponse(result)


@router.get("/interview-prep/{analysis_id}")
def interview_prep(
    analysis_id: str,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Get interview preparation data: strengths, gaps, scripts, advice."""
    validate_uuid(analysis_id)
    analysis = get_analysis_by_id(db, analysis_id)
    if not analysis:
        return JSONResponse({"error": "Analysis not found"}, status_code=404)

    return JSONResponse(
        {
            "company": analysis.company,
            "role": analysis.role,
            "score": analysis.score,
            "strengths": analysis.strengths or [],
            "gaps": analysis.gaps or [],
            "interview_scripts": analysis.interview_scripts or [],
            "advice": analysis.advice or "",
            "company_reputation": analysis.company_reputation or {},
        }
    )


@router.get("/cover-letters/{analysis_id}")
def cover_letters(
    analysis_id: str,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Get cover letters for an analysis."""
    validate_uuid(analysis_id)
    analysis = get_analysis_by_id(db, analysis_id)
    if not analysis:
        return JSONResponse({"error": "Analysis not found"}, status_code=404)

    letters = db.query(CoverLetter).filter(CoverLetter.analysis_id == analysis.id).all()
    return JSONResponse(
        {
            "cover_letters": [
                {
                    "id": str(cl.id),
                    "language": cl.language,
                    "content": cl.content,
                    "subject_lines": cl.subject_lines or [],
                    "created_at": cl.created_at.isoformat() if cl.created_at else None,
                }
                for cl in letters
            ]
        }
    )


@router.get("/contacts/search")
def contacts_search(
    db: DbSession,
    user: CurrentUser,
    q: str = Query(..., min_length=1, max_length=200, description="Search by name, company, or email"),
    limit: int = Query(20, ge=1, le=50),
) -> JSONResponse:
    """Search all contacts by name, company, or email."""
    contacts = search_all_contacts(db, query=q, limit=limit)
    return JSONResponse(
        {
            "contacts": [
                {
                    "id": str(c.id),
                    "name": c.name,
                    "email": c.email,
                    "phone": c.phone,
                    "company": c.company,
                    "linkedin_url": c.linkedin_url,
                    "notes": c.notes,
                    "source": c.source,
                }
                for c in contacts
            ]
        }
    )


@router.get("/followups/pending")
def pending_followups(
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Get candidature that need follow-up."""
    analyses = get_followup_alerts(db)
    return JSONResponse(
        {
            "pending_followups": [
                {
                    "id": str(a.id),
                    "company": a.company,
                    "role": a.role,
                    "applied_at": a.applied_at.isoformat() if a.applied_at else None,
                    "status": a.status or None,
                }
                for a in analyses
            ]
        }
    )


@router.get("/activity-summary")
def activity_summary(
    db: DbSession,
    user: CurrentUser,
    days: int = Query(7, ge=1, le=90, description="Number of days to summarize"),
) -> JSONResponse:
    """Get activity summary for the last N days."""
    from datetime import timedelta

    threshold = datetime.now(UTC) - timedelta(days=days)

    analyses = get_candidature_by_date_range(db, threshold, datetime.now(UTC))

    dashboard = get_dashboard(db)
    spending = get_spending(db)
    interviews = get_upcoming_interviews(db, days=days)

    total = len(analyses)
    avg_score = round(sum(a.score or 0 for a in analyses) / total, 1) if total > 0 else 0

    return JSONResponse(
        {
            "period_days": days,
            "new_candidature": total,
            "applied": sum(1 for a in analyses if a.status and a.status == "candidato"),
            "interviews_scheduled": len(interviews),
            "rejected": sum(1 for a in analyses if a.status and a.status == "scartato"),
            "avg_score": avg_score,
            "dashboard": dashboard,
            "spending": spending,
        }
    )
