"""Interview scheduling service — multi-round aware.

The service preserves the original 1-interview-per-analysis API
(``create_or_update_interview``, ``get_interview_by_analysis``,
``delete_interview``) by always operating on the LATEST round. Multi-round
mutations (advance to next round, log outcome) live in the new helpers
below and will be wired to the UI in PR-2.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from ..analysis.models import AnalysisStatus, JobAnalysis
from .models import Interview, InterviewOutcome


def _latest_round(db: Session, analysis_id: UUID | str) -> Interview | None:
    return (
        db.query(Interview).filter(Interview.analysis_id == analysis_id).order_by(Interview.round_number.desc()).first()
    )


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
    """Create or update the LATEST interview round for the given analysis.

    Back-compat: if no rounds exist, creates round 1; otherwise updates the
    most recent round in place. To start a new round, use ``create_next_round``.
    """
    analysis = db.query(JobAnalysis).filter(JobAnalysis.id == analysis_id).first()
    if not analysis:
        return None

    interview = _latest_round(db, analysis_id)

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
            round_number=1,
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
    """Return the LATEST interview round for an analysis (back-compat alias)."""
    return _latest_round(db, analysis_id)


def get_interview_rounds(db: Session, analysis_id: UUID | str) -> list[Interview]:
    """Return ALL rounds for an analysis, ordered by round_number ascending."""
    return db.query(Interview).filter(Interview.analysis_id == analysis_id).order_by(Interview.round_number.asc()).all()


def delete_interview(db: Session, analysis_id: UUID | str) -> bool:
    """Delete the LATEST interview round. Returns True if deleted.

    NB: removes only the most recent round; earlier rounds (history) are
    preserved. To wipe the entire interview history, delete each round or
    cascade via JobAnalysis deletion.
    """
    interview = _latest_round(db, analysis_id)
    if not interview:
        return False
    db.delete(interview)
    db.flush()
    return True


def set_outcome(db: Session, interview_id: UUID | str, outcome: InterviewOutcome | str) -> Interview | None:
    """Persist the outcome of a specific interview round.

    Idempotent: re-setting the same outcome is a no-op write. Returns the
    updated row, or ``None`` if the round does not exist.
    """
    val = outcome.value if isinstance(outcome, InterviewOutcome) else outcome
    if val not in {o.value for o in InterviewOutcome}:
        raise ValueError(f"Invalid interview outcome: {val!r}")

    interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if not interview:
        return None

    interview.outcome = val  # type: ignore[assignment]
    db.flush()
    return interview


def create_next_round(
    db: Session,
    analysis_id: UUID | str,
    *,
    scheduled_at: datetime,
    interview_type: str | None = None,
) -> Interview | None:
    """Append a new round AFTER the latest one (round_number += 1).

    Used when the candidate advances past the previous round (e.g. conoscitivo
    passed → schedule tecnico). The new row inherits no fields from the
    previous round; the caller can update it via ``create_or_update_interview``.
    """
    analysis = db.query(JobAnalysis).filter(JobAnalysis.id == analysis_id).first()
    if not analysis:
        return None

    latest = _latest_round(db, analysis_id)
    next_number = (int(latest.round_number) + 1) if latest else 1

    new_round = Interview(
        analysis_id=analysis_id,
        round_number=next_number,
        scheduled_at=scheduled_at,
        interview_type=interview_type,
    )
    db.add(new_round)
    db.flush()
    return new_round


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
