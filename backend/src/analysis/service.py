"""Analysis service: job analysis, result building, glassdoor merging."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy.orm import Session

from ..integrations.anthropic_client import analyze_job
from ..integrations.cache import CacheService
from ..integrations.glassdoor import fetch_glassdoor_rating
from .models import AnalysisSource, AnalysisStatus, JobAnalysis


def find_existing_analysis(db: Session, hash_value: str, model_id: str) -> JobAnalysis | None:
    """Find an existing analysis with the same content hash and model."""
    return (
        db.query(JobAnalysis)
        .filter(
            JobAnalysis.content_hash == hash_value,
            JobAnalysis.model_used == model_id,
        )
        .order_by(JobAnalysis.created_at.desc())
        .first()
    )


def run_analysis(
    db: Session,
    cv_text: str,
    cv_id: UUID,
    job_description: str,
    job_url: str,
    model: str,
    cache: CacheService | None = None,
    user_id: UUID | None = None,
    source: str = AnalysisSource.MANUAL.value,
) -> tuple[JobAnalysis, dict[str, Any]]:
    """Run a new analysis and persist it.

    ``source`` drives per-source notification aggregation. Callers should
    pass an explicit value from :class:`AnalysisSource` so the backlog
    notification center can split "N da valutare" cards per ingestion
    channel (extension / cowork / mcp / api).
    """
    result = analyze_job(cv_text, job_description, model, cache, db=db, user_id=user_id)
    _merge_glassdoor(result, db, cache)
    # Salary and news are fetched on-demand from the UI (not auto) to save
    # RapidAPI quota — 400 responses for Italian locations and strange titles
    # were burning calls fast. See fetch_salary / fetch_news endpoints.

    analysis = JobAnalysis(
        cv_id=cv_id,
        job_description=job_description,
        job_url=job_url,
        content_hash=result.get("content_hash", ""),
        job_summary=result.get("job_summary", ""),
        company=result.get("company", ""),
        role=result.get("role", ""),
        location=result.get("location", ""),
        work_mode=result.get("work_mode", ""),
        salary_info=result.get("salary_info", ""),
        score=result.get("score", 0),
        recommendation=result.get("recommendation", ""),
        strengths=result.get("strengths", []),
        gaps=result.get("gaps", []),
        interview_scripts=result.get("interview_scripts", []),
        advice=result.get("advice", ""),
        company_reputation=result.get("company_reputation", {}),
        salary_data=result.get("salary_data") or None,
        company_news=result.get("company_news") or None,
        career_track=result.get("career_track") or None,
        track_reason=result.get("track_reason") or None,
        benefits=result.get("benefits") or None,
        recruiter_info=result.get("recruiter_info") or None,
        experience_required=result.get("experience_required") or None,
        full_response=result.get("full_response", ""),
        model_used=result.get("model_used", ""),
        tokens_input=result.get("tokens", {}).get("input", 0),
        tokens_output=result.get("tokens", {}).get("output", 0),
        cost_usd=result.get("cost_usd", 0.0),
        source=source,
    )
    db.add(analysis)
    db.flush()
    # Nudge every connected browser tab to refresh notifications/history
    # right now instead of waiting for the next 30s polling tick.
    from ..notification_center.sse import broadcast_sync

    broadcast_sync("analysis:new")
    return analysis, result


_REBUILD_EXTRA_KEYS = (
    "score_label",
    "potential_score",
    "gap_timeline",
    "confidence",
    "confidence_reason",
    "summary",
    "application_method",
)


def _base_result(analysis: JobAnalysis, from_cache: bool) -> dict[str, Any]:
    """Build the always-present fields of the result dict (pre-extra merge)."""
    tokens_input = analysis.tokens_input or 0
    tokens_output = analysis.tokens_output or 0
    return {
        "company": analysis.company,
        "role": analysis.role,
        "location": analysis.location,
        "work_mode": analysis.work_mode,
        "salary_info": analysis.salary_info,
        "score": analysis.score,
        "recommendation": analysis.recommendation,
        "job_summary": analysis.job_summary,
        "strengths": analysis.strengths or [],
        "gaps": analysis.gaps or [],
        "interview_scripts": analysis.interview_scripts or [],
        "advice": analysis.advice or "",
        "company_reputation": analysis.company_reputation or {},
        "salary_data": analysis.salary_data or {},
        "company_news": analysis.company_news or [],
        "career_track": analysis.career_track or "hybrid_a_b",
        "track_reason": analysis.track_reason or "",
        "benefits": analysis.benefits or [],
        "recruiter_info": analysis.recruiter_info or {},
        "experience_required": analysis.experience_required or {},
        "summary": "",
        "model_used": analysis.model_used,
        "tokens": {
            "input": tokens_input,
            "output": tokens_output,
            "total": tokens_input + tokens_output,
        },
        "cost_usd": analysis.cost_usd or 0.0,
        "from_cache": from_cache,
    }


def rebuild_result(analysis: JobAnalysis, from_cache: bool = False) -> dict[str, Any]:
    """Rebuild the full result dict from a stored analysis row."""
    result = _base_result(analysis, from_cache)
    full = _parse_full_response(cast(str, analysis.full_response))
    for key in _REBUILD_EXTRA_KEYS:
        if key in full:
            result[key] = full[key]
    return result


def update_status(db: Session, analysis: JobAnalysis, new_status: AnalysisStatus) -> None:
    """Update analysis status, setting applied_at when relevant."""
    analysis.status = new_status  # type: ignore[assignment]
    if new_status in (AnalysisStatus.APPLIED, AnalysisStatus.INTERVIEW) and not analysis.applied_at:
        analysis.applied_at = datetime.now(UTC)  # type: ignore[assignment]
    db.flush()


def get_analysis_by_id(db: Session, analysis_id: str, user_id: UUID | None = None) -> JobAnalysis | None:
    """Fetch a single analysis by UUID, optionally scoped to the user that owns the CV.

    Passing ``user_id=None`` bypasses the ownership filter — use ONLY for
    trusted internal callers (batch worker background task, admin tools)
    that have already authorized the request some other way. Route
    handlers with a user session MUST pass the authenticated user's id
    to prevent BOLA (broken object-level authorization).

    Returns None if the id is invalid, the row is missing, or the row
    belongs to a different user.
    """
    try:
        uid = UUID(analysis_id)
    except (ValueError, AttributeError):
        return None

    q = db.query(JobAnalysis).filter(JobAnalysis.id == uid)
    if user_id is not None:
        from ..cv.models import CVProfile

        user_cv_ids = db.query(CVProfile.id).filter(CVProfile.user_id == user_id)
        q = q.filter(JobAnalysis.cv_id.in_(user_cv_ids))
    return q.first()


def get_recent_analyses(db: Session, limit: int = 50) -> list[JobAnalysis]:
    """Return the most recent analyses ordered by creation date."""
    return db.query(JobAnalysis).order_by(JobAnalysis.created_at.desc()).limit(limit).all()


def get_candidature(db: Session, status: str | None = None, limit: int = 50) -> list[JobAnalysis]:
    """Get candidature optionally filtered by status."""
    q = db.query(JobAnalysis)
    if status:
        try:
            status_enum = AnalysisStatus(status)
        except ValueError:
            return []
        q = q.filter(JobAnalysis.status == status_enum)
    return q.order_by(JobAnalysis.created_at.desc()).limit(min(limit, 100)).all()


def search_candidature(db: Session, query: str, limit: int = 20) -> list[JobAnalysis]:
    """Search candidature by company or role (case-insensitive)."""
    pattern = f"%{query}%"
    return (
        db.query(JobAnalysis)
        .filter((JobAnalysis.company.ilike(pattern)) | (JobAnalysis.role.ilike(pattern)))
        .order_by(JobAnalysis.created_at.desc())
        .limit(min(limit, 50))
        .all()
    )


def get_top_candidature(db: Session, limit: int = 10) -> list[JobAnalysis]:
    """Get top-scored candidature (excluding rejected)."""
    return (
        db.query(JobAnalysis)
        .filter(JobAnalysis.status != AnalysisStatus.REJECTED)
        .order_by(JobAnalysis.score.desc())
        .limit(min(limit, 50))
        .all()
    )


def get_candidature_by_date_range(db: Session, date_from: datetime, date_to: datetime) -> list[JobAnalysis]:
    """Get candidature created within a date range."""
    return (
        db.query(JobAnalysis)
        .filter(
            JobAnalysis.created_at >= date_from,
            JobAnalysis.created_at <= date_to,
        )
        .order_by(JobAnalysis.created_at.desc())
        .all()
    )


def get_stale_candidature(db: Session, days: int = 7) -> list[JobAnalysis]:
    """Get candidature with status 'candidato' that haven't been updated in N days."""
    threshold = datetime.now(UTC) - timedelta(days=days)
    return (
        db.query(JobAnalysis)
        .filter(
            JobAnalysis.status == AnalysisStatus.APPLIED,
            JobAnalysis.applied_at.isnot(None),
            JobAnalysis.applied_at <= threshold,
            JobAnalysis.followed_up == False,  # noqa: E712
        )
        .order_by(JobAnalysis.applied_at.asc())
        .all()
    )


def _merge_glassdoor(result: dict[str, Any], db: Session, cache: CacheService | None = None) -> None:
    """Merge Glassdoor API data into result's company_reputation."""
    company = result.get("company", "")
    if not company:
        return

    gd = fetch_glassdoor_rating(company, db, cache)
    if not gd:
        return

    rep = result.get("company_reputation")
    if not isinstance(rep, dict):
        rep = {}
    review_count = gd.get("review_count", 0)
    rep["glassdoor_estimate"] = f"{gd['glassdoor_rating']:.1f}/5"
    rep["review_count"] = review_count
    rep["sub_ratings"] = gd.get("sub_ratings", {})
    rep["ceo_name"] = gd.get("ceo_name", "")
    rep["ceo_approval"] = gd.get("ceo_approval")
    rep["recommend_to_friend"] = gd.get("recommend_to_friend")
    rep["business_outlook"] = gd.get("business_outlook")
    rep["glassdoor_url"] = gd.get("glassdoor_url", "")
    for field in ("industry", "company_size", "website", "headquarters", "founded", "revenue"):
        if gd.get(field):
            rep[field] = gd[field]
    rep["source"] = "glassdoor_api"
    count_fmt = f"{review_count:,}".replace(",", ".") if review_count else "n/d"
    rep["note"] = f"Fonte: Glassdoor ({count_fmt} recensioni)"
    result["company_reputation"] = rep


def _merge_salary(result: dict[str, Any], db: Session) -> None:
    """Merge salary API data into result."""
    role = result.get("role", "")
    if not role:
        return
    from ..integrations.salary import fetch_salary_data

    salary = fetch_salary_data(role, result.get("location"), db)
    if salary:
        result["salary_data"] = salary


def _merge_news(result: dict[str, Any], db: Session) -> None:
    """Merge company news into result."""
    company = result.get("company", "")
    if not company:
        return
    from ..integrations.news import fetch_company_news

    news = fetch_company_news(company, db)
    if news:
        result["company_news"] = news


def _parse_full_response(raw: str) -> dict[str, Any]:
    """Parse stored full_response JSON, handling markdown wrapping."""
    if not raw:
        return {}
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        return cast(dict[str, Any], json.loads(text))
    except (json.JSONDecodeError, TypeError):
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                return cast(dict[str, Any], json.loads(text[start : end + 1]))
            except (json.JSONDecodeError, TypeError):
                pass
    return {}
