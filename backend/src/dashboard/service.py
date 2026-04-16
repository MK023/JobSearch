"""Dashboard and spending service."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..analysis.models import AnalysisStatus, AppSettings, JobAnalysis
from ..config import settings as app_settings
from ..cover_letter.models import CoverLetter


def get_or_create_settings(db: Session) -> AppSettings:
    """Fetch the singleton AppSettings row, creating it if missing."""
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
        s.today_date = today  # type: ignore[assignment]
        s.today_cost_usd = 0.0  # type: ignore[assignment]
        s.today_tokens_input = 0  # type: ignore[assignment]
        s.today_tokens_output = 0  # type: ignore[assignment]
        s.today_analyses = 0  # type: ignore[assignment]


def check_budget_available(db: Session) -> tuple[bool, str]:
    """Check if budget allows further spending. Returns (ok, message)."""
    s = get_or_create_settings(db)
    budget = float(s.anthropic_budget or 0)
    if budget <= 0:
        return True, ""  # No budget set = no limit
    total_cost = float(s.total_cost_usd or 0)
    remaining = budget - total_cost
    if remaining <= 0:
        return False, f"Budget esaurito! Speso ${total_cost:.4f} su ${budget:.2f}"
    return True, ""


def add_spending(db: Session, cost: float, tokens_in: int, tokens_out: int, is_analysis: bool = True) -> None:
    """Update running totals after an insert."""
    s = get_or_create_settings(db)
    _check_today_reset(s)
    s.total_cost_usd = round(float(s.total_cost_usd or 0) + cost, 6)  # type: ignore[arg-type]
    s.total_tokens_input = int(s.total_tokens_input or 0) + tokens_in  # type: ignore[assignment]
    s.total_tokens_output = int(s.total_tokens_output or 0) + tokens_out  # type: ignore[assignment]
    s.today_cost_usd = round(float(s.today_cost_usd or 0) + cost, 6)  # type: ignore[arg-type]
    s.today_tokens_input = int(s.today_tokens_input or 0) + tokens_in  # type: ignore[assignment]
    s.today_tokens_output = int(s.today_tokens_output or 0) + tokens_out  # type: ignore[assignment]
    if is_analysis:
        s.total_analyses = int(s.total_analyses or 0) + 1  # type: ignore[assignment]
        s.today_analyses = int(s.today_analyses or 0) + 1  # type: ignore[assignment]
    else:
        s.total_cover_letters = int(s.total_cover_letters or 0) + 1  # type: ignore[assignment]


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
    s.total_cost_usd = round(max(float(s.total_cost_usd or 0) - cost, 0), 6)  # type: ignore[arg-type]
    s.total_tokens_input = max(int(s.total_tokens_input or 0) - tokens_in, 0)  # type: ignore[arg-type]
    s.total_tokens_output = max(int(s.total_tokens_output or 0) - tokens_out, 0)  # type: ignore[arg-type]
    if is_analysis:
        s.total_analyses = max(int(s.total_analyses or 0) - 1, 0)  # type: ignore[arg-type]
    else:
        s.total_cover_letters = max(int(s.total_cover_letters or 0) - 1, 0)  # type: ignore[arg-type]
    if created_today:
        s.today_cost_usd = round(max(float(s.today_cost_usd or 0) - cost, 0), 6)  # type: ignore[arg-type]
        s.today_tokens_input = max(int(s.today_tokens_input or 0) - tokens_in, 0)  # type: ignore[arg-type]
        s.today_tokens_output = max(int(s.today_tokens_output or 0) - tokens_out, 0)  # type: ignore[arg-type]
        if is_analysis:
            s.today_analyses = max(int(s.today_analyses or 0) - 1, 0)  # type: ignore[arg-type]


def get_spending(db: Session) -> dict[str, Any]:
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
    """Set the Anthropic API budget and return the persisted value."""
    s = get_or_create_settings(db)
    s.anthropic_budget = max(budget, 0)  # type: ignore[arg-type]
    db.flush()
    return round(float(s.anthropic_budget or 0), 2)


def get_dashboard(db: Session) -> dict[str, Any]:
    """Build dashboard stats from the FULL database — no rolling window.

    Counts map directly onto AnalysisStatus values so the UI shows the
    cumulative state of the job hunt, not an arbitrary last-N slice.
    """

    def _count(*statuses: AnalysisStatus) -> int:
        q = db.query(func.count(JobAnalysis.id))
        if statuses:
            q = q.filter(JobAnalysis.status.in_([s.value for s in statuses]))
        return int(q.scalar() or 0)

    total = _count()
    applied = _count(AnalysisStatus.APPLIED)
    interviews = _count(AnalysisStatus.INTERVIEW)
    offers = _count(AnalysisStatus.OFFER)
    skipped = _count(AnalysisStatus.REJECTED)
    pending = _count(AnalysisStatus.PENDING)

    # Average score across analyses the user actually sent — single source of truth
    # for "quality of my outgoing pipeline".
    avg_score_raw = (
        db.query(func.avg(JobAnalysis.score))
        .filter(
            JobAnalysis.status.in_(
                [
                    AnalysisStatus.APPLIED.value,
                    AnalysisStatus.INTERVIEW.value,
                    AnalysisStatus.OFFER.value,
                ]
            )
        )
        .scalar()
    )
    avg_score = round(float(avg_score_raw), 1) if avg_score_raw is not None else 0.0

    threshold = datetime.now(UTC) - timedelta(days=app_settings.followup_reminder_days)
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

    top_row = (
        db.query(JobAnalysis)
        .filter(JobAnalysis.status != AnalysisStatus.REJECTED.value)
        .order_by(JobAnalysis.score.desc())
        .first()
    )

    return {
        "total": total,
        "applied": applied,
        "interviews": interviews,
        "offers": offers,
        "skipped": skipped,
        "pending": pending,
        "avg_score": avg_score,
        "followup_count": followup_count,
        "top_match": ({"role": top_row.role, "company": top_row.company, "score": top_row.score} if top_row else None),
    }


def get_followup_alerts(db: Session) -> list[JobAnalysis]:
    """Get analyses needing follow-up (applied > N days ago, not followed up)."""
    threshold = datetime.now(UTC) - timedelta(days=app_settings.followup_reminder_days)
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
        if a and cl:
            s.total_cost_usd = round(float(a[0]) + float(cl[0]), 6)  # type: ignore[arg-type]
            s.total_tokens_input = int(a[1]) + int(cl[1])  # type: ignore[assignment]
            s.total_tokens_output = int(a[2]) + int(cl[2])  # type: ignore[assignment]
            s.total_analyses = int(a[3])  # type: ignore[assignment]
            s.total_cover_letters = int(cl[3])  # type: ignore[assignment]
            s.today_date = date.today().isoformat()  # type: ignore[assignment]
        db.flush()
