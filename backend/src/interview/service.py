"""Interview scheduling service."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from ..analysis.models import AnalysisStatus, JobAnalysis
from .models import Interview


def create_or_update_interview(
    db: Session,
    analysis_id: UUID,
    *,
    scheduled_at: datetime,
    ends_at: datetime | None = None,
    interview_type: str | None = None,
    recruiter_name: str | None = None,
    recruiter_email: str | None = None,
    meeting_link: str | None = None,
    phone_number: str | None = None,
    phone_pin: str | None = None,
    location: str | None = None,
    notes: str | None = None,
) -> Interview | None:
    """Create or update an interview for the given analysis."""
    analysis = db.query(JobAnalysis).filter(JobAnalysis.id == analysis_id).first()
    if not analysis:
        return None

    interview = db.query(Interview).filter(Interview.analysis_id == analysis_id).first()

    if interview:
        interview.scheduled_at = scheduled_at
        interview.ends_at = ends_at
        interview.interview_type = interview_type
        interview.recruiter_name = recruiter_name
        interview.recruiter_email = recruiter_email
        interview.meeting_link = meeting_link
        interview.phone_number = phone_number
        interview.phone_pin = phone_pin
        interview.location = location
        interview.notes = notes
    else:
        interview = Interview(
            analysis_id=analysis_id,
            scheduled_at=scheduled_at,
            ends_at=ends_at,
            interview_type=interview_type,
            recruiter_name=recruiter_name,
            recruiter_email=recruiter_email,
            meeting_link=meeting_link,
            phone_number=phone_number,
            phone_pin=phone_pin,
            location=location,
            notes=notes,
        )
        db.add(interview)

    db.flush()
    return interview


def get_interview_by_analysis(db: Session, analysis_id: UUID) -> Interview | None:
    """Get interview for an analysis."""
    return db.query(Interview).filter(Interview.analysis_id == analysis_id).first()


def delete_interview(db: Session, analysis_id: UUID) -> bool:
    """Delete interview for an analysis. Returns True if deleted."""
    interview = db.query(Interview).filter(Interview.analysis_id == analysis_id).first()
    if not interview:
        return False
    db.delete(interview)
    db.flush()
    return True


def get_upcoming_interviews(db: Session, hours: int = 48) -> list[dict]:
    """Get interviews scheduled within the next N hours."""
    now = datetime.now(UTC)
    cutoff = now + timedelta(hours=hours)

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
            "interview_type": i.interview_type,
            "meeting_link": i.meeting_link,
        }
        for i, a in rows
    ]
