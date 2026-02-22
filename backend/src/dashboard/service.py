"""Dashboard and spending service."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..analysis.models import AnalysisStatus, AppSettings, JobAnalysis
from ..cover_letter.models import CoverLetter


def get_or_create_settings(db: Session) -> AppSettings:
    s = db.query(AppSettings).first()
    if not s:
        s = AppSettings(id=1, anthropic_budget=0.0)
        db.add(s)
        db.flush()
    return s


def _check_today_reset(s: AppSettings) -> None:
    """Reset daily counters if the date has changed."""
    today = date.today().isoformat()
    if (s.today_date or "") != today:
        s.today_date = today
        s.today_cost_usd = 0.0
        s.today_tokens_input = 0
        s.today_tokens_output = 0
        s.today_analyses = 0


def add_spending(db: Session, cost: float, tokens_in: int, tokens_out: int, is_analysis: bool = True) -> None:
    """Update running totals after an insert."""
    s = get_or_create_settings(db)
    _check_today_reset(s)
    s.total_cost_usd = round((s.total_cost_usd or 0) + cost, 6)
    s.total_tokens_input = (s.total_tokens_input or 0) + tokens_in
    s.total_tokens_output = (s.total_tokens_output or 0) + tokens_out
    s.today_cost_usd = round((s.today_cost_usd or 0) + cost, 6)
    s.today_tokens_input = (s.today_tokens_input or 0) + tokens_in
    s.today_tokens_output = (s.today_tokens_output or 0) + tokens_out
    if is_analysis:
        s.total_analyses = (s.total_analyses or 0) + 1
        s.today_analyses = (s.today_analyses or 0) + 1
    else:
        s.total_cover_letters = (s.total_cover_letters or 0) + 1


def remove_spending(
    db: Session,
    cost: float,
    tokens_in: int,
    tokens_out: int,
    is_analysis: bool = True,
    created_today: bool = False,
) -> None:
    """Update running totals after a delete."""
    s = get_or_create_settings(db)
    _check_today_reset(s)
    s.total_cost_usd = round(max((s.total_cost_usd or 0) - cost, 0), 6)
    s.total_tokens_input = max((s.total_tokens_input or 0) - tokens_in, 0)
    s.total_tokens_output = max((s.total_tokens_output or 0) - tokens_out, 0)
    if is_analysis:
        s.total_analyses = max((s.total_analyses or 0) - 1, 0)
    else:
        s.total_cover_letters = max((s.total_cover_letters or 0) - 1, 0)
    if created_today:
        s.today_cost_usd = round(max((s.today_cost_usd or 0) - cost, 0), 6)
        s.today_tokens_input = max((s.today_tokens_input or 0) - tokens_in, 0)
        s.today_tokens_output = max((s.today_tokens_output or 0) - tokens_out, 0)
        if is_analysis:
            s.today_analyses = max((s.today_analyses or 0) - 1, 0)


def get_spending(db: Session) -> dict:
    """Get current spending totals."""
    s = get_or_create_settings(db)
    _check_today_reset(s)
    db.flush()
    budget = float(s.anthropic_budget or 0)
    total_cost = float(s.total_cost_usd or 0)
    remaining = round(budget - total_cost, 4) if budget > 0 else None
    return {
        "budget": round(budget, 2),
        "total_cost_usd": round(total_cost, 4),
        "remaining": remaining,
        "total_analyses": int(s.total_analyses or 0),
        "total_tokens_input": int(s.total_tokens_input or 0),
        "total_tokens_output": int(s.total_tokens_output or 0),
        "today_cost_usd": round(float(s.today_cost_usd or 0), 4),
        "today_analyses": int(s.today_analyses or 0),
        "today_tokens_input": int(s.today_tokens_input or 0),
        "today_tokens_output": int(s.today_tokens_output or 0),
    }


def update_budget(db: Session, budget: float) -> float:
    s = get_or_create_settings(db)
    s.anthropic_budget = max(budget, 0)
    db.flush()
    return round(s.anthropic_budget, 2)


def get_dashboard(db: Session) -> dict:
    """Build dashboard stats."""
    analyses = db.query(JobAnalysis).order_by(JobAnalysis.created_at.desc()).limit(50).all()
    total = len(analyses)
    applied = sum(1 for a in analyses if a.status in (AnalysisStatus.APPLIED, AnalysisStatus.INTERVIEW))
    avg_score = round(sum(a.score or 0 for a in analyses) / total, 1) if total else 0

    threshold = datetime.now(UTC) - timedelta(days=5)
    followup_count = (
        db.query(JobAnalysis)
        .filter(
            JobAnalysis.status.in_([AnalysisStatus.APPLIED, AnalysisStatus.INTERVIEW]),
            JobAnalysis.applied_at.isnot(None),
            JobAnalysis.applied_at <= threshold,
            JobAnalysis.followed_up == False,  # noqa: E712
        )
        .count()
    )

    non_rejected = [a for a in analyses if a.status != AnalysisStatus.REJECTED]
    top = max(non_rejected, key=lambda a: a.score or 0, default=None)

    return {
        "total": total,
        "applied": applied,
        "interviews": sum(1 for a in analyses if a.status == AnalysisStatus.INTERVIEW),
        "skipped": sum(1 for a in analyses if a.status == AnalysisStatus.REJECTED),
        "pending": sum(1 for a in analyses if a.status == AnalysisStatus.PENDING),
        "avg_score": avg_score,
        "followup_count": followup_count,
        "top_match": ({"role": top.role, "company": top.company, "score": top.score} if top else None),
    }


def get_followup_alerts(db: Session) -> list[JobAnalysis]:
    """Get analyses needing follow-up (applied > 5 days ago, not followed up)."""
    threshold = datetime.now(UTC) - timedelta(days=5)
    return (
        db.query(JobAnalysis)
        .filter(
            JobAnalysis.status.in_([AnalysisStatus.APPLIED, AnalysisStatus.INTERVIEW]),
            JobAnalysis.applied_at.isnot(None),
            JobAnalysis.applied_at <= threshold,
            JobAnalysis.followed_up == False,  # noqa: E712
        )
        .order_by(JobAnalysis.applied_at.asc())
        .all()
    )


def get_active_applications(db: Session) -> list[JobAnalysis]:
    """Get analyses with active application status."""
    return (
        db.query(JobAnalysis)
        .filter(JobAnalysis.status.in_([AnalysisStatus.APPLIED, AnalysisStatus.INTERVIEW]))
        .order_by(JobAnalysis.created_at.desc())
        .all()
    )


def seed_spending_totals(db: Session) -> None:
    """Calculate initial totals from existing data if app_settings is empty."""
    s = get_or_create_settings(db)
    existing = db.query(func.count(JobAnalysis.id)).scalar() or 0

    if (s.total_analyses or 0) == 0 and existing > 0:
        a = db.query(
            func.coalesce(func.sum(JobAnalysis.cost_usd), 0.0),
            func.coalesce(func.sum(JobAnalysis.tokens_input), 0),
            func.coalesce(func.sum(JobAnalysis.tokens_output), 0),
            func.count(JobAnalysis.id),
        ).first()
        cl = db.query(
            func.coalesce(func.sum(CoverLetter.cost_usd), 0.0),
            func.coalesce(func.sum(CoverLetter.tokens_input), 0),
            func.coalesce(func.sum(CoverLetter.tokens_output), 0),
            func.count(CoverLetter.id),
        ).first()
        s.total_cost_usd = round(float(a[0]) + float(cl[0]), 6)
        s.total_tokens_input = int(a[1]) + int(cl[1])
        s.total_tokens_output = int(a[2]) + int(cl[2])
        s.total_analyses = int(a[3])
        s.total_cover_letters = int(cl[3])
        s.today_date = date.today().isoformat()
        db.flush()
