"""Interview scheduling service."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from ..analysis.models import AnalysisStatus, JobAnalysis
from .models import Interview


def create_or_update_interview(
    db: Session,
    analysis_id: UUID | str,
    *,
    scheduled_at: datetime,
    ends_at: datetime | None = None,
    platform: str | None = None,
    interview_type: str | None = None,
    interviewer_name: str | None = None,
    recruiter_name: str | None = None,
    recruiter_email: str | None = None,
    meeting_link: str | None = None,
    meeting_id: str | None = None,
    phone_number: str | None = None,
    access_pin: str | None = None,
    location: str | None = None,
    notes: str | None = None,
) -> Interview | None:
    """Create or update an interview for the given analysis."""
    analysis = db.query(JobAnalysis).filter(JobAnalysis.id == analysis_id).first()
    if not analysis:
        return None

    interview = db.query(Interview).filter(Interview.analysis_id == analysis_id).first()

    if interview:
        interview.scheduled_at = scheduled_at  # type: ignore[assignment]
        interview.ends_at = ends_at  # type: ignore[assignment]
        interview.platform = platform  # type: ignore[assignment]
        interview.interview_type = interview_type  # type: ignore[assignment]
        interview.interviewer_name = interviewer_name  # type: ignore[assignment]
        interview.recruiter_name = recruiter_name  # type: ignore[assignment]
        interview.recruiter_email = recruiter_email  # type: ignore[assignment]
        interview.meeting_link = meeting_link  # type: ignore[assignment]
        interview.meeting_id = meeting_id  # type: ignore[assignment]
        interview.phone_number = phone_number  # type: ignore[assignment]
        interview.access_pin = access_pin  # type: ignore[assignment]
        interview.location = location  # type: ignore[assignment]
        interview.notes = notes  # type: ignore[assignment]
    else:
        interview = Interview(
            analysis_id=analysis_id,
            scheduled_at=scheduled_at,
            ends_at=ends_at,
            platform=platform,
            interview_type=interview_type,
            interviewer_name=interviewer_name,
            recruiter_name=recruiter_name,
            recruiter_email=recruiter_email,
            meeting_link=meeting_link,
            meeting_id=meeting_id,
            phone_number=phone_number,
            access_pin=access_pin,
            location=location,
            notes=notes,
        )
        db.add(interview)

    db.flush()
    return interview


def get_interview_by_analysis(db: Session, analysis_id: UUID | str) -> Interview | None:
    """Get interview for an analysis."""
    return db.query(Interview).filter(Interview.analysis_id == analysis_id).first()


def delete_interview(db: Session, analysis_id: UUID | str) -> bool:
    """Delete interview for an analysis. Returns True if deleted."""
    interview = db.query(Interview).filter(Interview.analysis_id == analysis_id).first()
    if not interview:
        return False
    db.delete(interview)
    db.flush()
    return True


def get_upcoming_interviews(db: Session, hours: int = 48, days: int | None = None) -> list[dict[str, Any]]:
    """Get interviews scheduled within the next N hours (or N days if specified)."""
    now = datetime.now(UTC)
    cutoff = now + timedelta(days=days) if days is not None else now + timedelta(hours=hours)

    rows = (
        db.query(Interview, JobAnalysis)
        .join(JobAnalysis, Interview.analysis_id == JobAnalysis.id)
        .filter(
            JobAnalysis.status == AnalysisStatus.INTERVIEW,
            Interview.scheduled_at > now,
            Interview.scheduled_at <= cutoff,
        )
        .order_by(Interview.scheduled_at.asc())
        .all()
    )

    return [
        {
            "analysis_id": str(a.id),
            "company": a.company,
            "role": a.role,
            "scheduled_at": i.scheduled_at.isoformat(),
            "ends_at": i.ends_at.isoformat() if i.ends_at else None,
            "date_display": format_date(i.scheduled_at),
            "time_display": format_time(i.scheduled_at, i.ends_at),
            "platform": i.platform,
            "interview_type": i.interview_type,
            "meeting_link": i.meeting_link,
        }
        for i, a in rows
    ]


_MONTHS_IT = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]


def format_date(dt: datetime) -> str:
    """Format date as '15 mar 2026'."""
    return f"{dt.day} {_MONTHS_IT[dt.month - 1]} {dt.year}"


def format_time(start: datetime, end: datetime | None) -> str:
    """Format time range as '14:30' or '14:30 – 15:30'."""
    t = f"{start.strftime('%H:%M')}"
    if end:
        t += f" – {end.strftime('%H:%M')}"
    return t
