"""Analysis service: job analysis, result building, glassdoor merging."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy.orm import Session

from ..integrations.anthropic_client import analyze_job
from ..integrations.cache import CacheService
from ..integrations.glassdoor import fetch_glassdoor_rating
from .models import AnalysisStatus, JobAnalysis


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
) -> tuple[JobAnalysis, dict[str, Any]]:
    """Run a new analysis and persist it."""
    result = analyze_job(cv_text, job_description, model, cache)
    _merge_glassdoor(result, db)

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
        full_response=result.get("full_response", ""),
        model_used=result.get("model_used", ""),
        tokens_input=result.get("tokens", {}).get("input", 0),
        tokens_output=result.get("tokens", {}).get("output", 0),
        cost_usd=result.get("cost_usd", 0.0),
    )
    db.add(analysis)
    db.flush()
    return analysis, result


def rebuild_result(analysis: JobAnalysis, from_cache: bool = False) -> dict[str, Any]:
    """Rebuild the full result dict from a stored analysis row."""
    result = {
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
        "summary": "",
        "model_used": analysis.model_used,
        "tokens": {
            "input": analysis.tokens_input or 0,
            "output": analysis.tokens_output or 0,
            "total": (analysis.tokens_input or 0) + (analysis.tokens_output or 0),
        },
        "cost_usd": analysis.cost_usd or 0.0,
        "from_cache": from_cache,
    }

    # Extract extra fields from full_response
    full = _parse_full_response(cast(str, analysis.full_response))
    for key in (
        "score_label",
        "potential_score",
        "gap_timeline",
        "confidence",
        "confidence_reason",
        "summary",
        "application_method",
    ):
        if key in full:
            result[key] = full[key]

    return result


def update_status(db: Session, analysis: JobAnalysis, new_status: AnalysisStatus) -> None:
    """Update analysis status, setting applied_at when relevant."""
    analysis.status = new_status  # type: ignore[assignment]
    if new_status in (AnalysisStatus.APPLIED, AnalysisStatus.INTERVIEW) and not analysis.applied_at:
        analysis.applied_at = datetime.now(UTC)  # type: ignore[assignment]
    db.flush()


def get_analysis_by_id(db: Session, analysis_id: str) -> JobAnalysis | None:
    """Fetch a single analysis by its UUID string, returning None if invalid or missing."""
    try:
        uid = UUID(analysis_id)
    except (ValueError, AttributeError):
        return None
    return db.query(JobAnalysis).filter(JobAnalysis.id == uid).first()


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


def _merge_glassdoor(result: dict[str, Any], db: Session) -> None:
    """Merge Glassdoor API data into result's company_reputation."""
    company = result.get("company", "")
    if not company:
        return

    gd = fetch_glassdoor_rating(company, db)
    if not gd:
        return

    rep = result.get("company_reputation", {}) or {}
    review_count = gd.get("review_count", 0)
    rep["glassdoor_estimate"] = f"{gd['glassdoor_rating']:.1f}/5"
    rep["review_count"] = review_count
    rep["sub_ratings"] = gd.get("sub_ratings", {})
    rep["ceo_name"] = gd.get("ceo_name", "")
    rep["ceo_approval"] = gd.get("ceo_approval")
    rep["recommend_to_friend"] = gd.get("recommend_to_friend")
    rep["business_outlook"] = gd.get("business_outlook")
    rep["glassdoor_url"] = gd.get("glassdoor_url", "")
    rep["source"] = "glassdoor_api"
    count_fmt = f"{review_count:,}".replace(",", ".") if review_count else "n/d"
    rep["note"] = f"Fonte: Glassdoor ({count_fmt} recensioni)"
    result["company_reputation"] = rep


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
