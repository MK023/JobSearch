"""Interview JSON API routes."""

import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..analysis.models import AnalysisStatus
from ..analysis.service import get_analysis_by_id, update_status
from ..audit.service import audit
from ..dependencies import CurrentUser, DbSession, validate_uuid
from .models import Interview, InterviewOutcome
from .service import (
    create_next_round,
    create_or_update_interview,
    delete_interview,
    get_interview_by_analysis,
    get_upcoming_interviews,
    set_outcome,
)

router = APIRouter(tags=["interviews"])


VALID_PLATFORMS = {"google_meet", "teams", "zoom", "phone", "in_person", "other"}
VALID_INTERVIEW_TYPES = {"tecnico", "hr", "conoscitivo", "finale", "other"}
EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
URL_RE = re.compile(r"^https?://", re.IGNORECASE)


class InterviewPayload(BaseModel):
    """Input schema for creating or updating an interview."""

    scheduled_at: str
    ends_at: str | None = None
    platform: str | None = Field(None, max_length=20)
    interview_type: str | None = Field(None, max_length=20)
    interviewer_name: str | None = Field(None, max_length=255)
    recruiter_name: str | None = Field(None, max_length=255)
    recruiter_email: str | None = Field(None, max_length=255)
    meeting_link: str | None = Field(None, max_length=500)
    meeting_id: str | None = Field(None, max_length=100)
    phone_number: str | None = Field(None, max_length=50)
    access_pin: str | None = Field(None, max_length=20)
    location: str | None = Field(None, max_length=500)
    notes: str | None = Field(None, max_length=2000)


@router.post("/interviews/{analysis_id}")
def upsert_interview(
    request: Request,
    analysis_id: str,
    payload: InterviewPayload,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Create or update an interview with validation and status transition."""
    validate_uuid(analysis_id)
    analysis = get_analysis_by_id(db, analysis_id)
    if not analysis:
        return JSONResponse({"error": "Analysis not found"}, status_code=404)

    try:
        scheduled = datetime.fromisoformat(payload.scheduled_at)
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=UTC)
    except ValueError:
        return JSONResponse({"error": "Invalid scheduled_at format"}, status_code=400)

    # No scheduling far in the past (allow 24h buffer for timezone edge cases)
    if scheduled < datetime.now(UTC) - timedelta(hours=24):
        return JSONResponse({"error": "Non puoi prenotare un colloquio nel passato"}, status_code=400)

    ends = None
    if payload.ends_at:
        try:
            ends = datetime.fromisoformat(payload.ends_at)
            if ends.tzinfo is None:
                ends = ends.replace(tzinfo=UTC)
        except ValueError:
            return JSONResponse({"error": "Invalid ends_at format"}, status_code=400)
        if ends <= scheduled:
            return JSONResponse({"error": "L'ora di fine deve essere dopo l'ora di inizio"}, status_code=400)

    if payload.platform and payload.platform not in VALID_PLATFORMS:
        return JSONResponse({"error": f"Piattaforma non valida: {payload.platform}"}, status_code=400)
    if payload.interview_type and payload.interview_type not in VALID_INTERVIEW_TYPES:
        return JSONResponse({"error": f"Tipo colloquio non valido: {payload.interview_type}"}, status_code=400)
    if payload.recruiter_email and not EMAIL_RE.match(payload.recruiter_email):
        return JSONResponse({"error": "Formato email non valido"}, status_code=400)
    if payload.meeting_link and not URL_RE.match(payload.meeting_link):
        return JSONResponse({"error": "Il link deve iniziare con http:// o https://"}, status_code=400)

    create_or_update_interview(
        db,
        str(analysis.id),
        scheduled_at=scheduled,
        ends_at=ends,
        platform=payload.platform,
        interview_type=payload.interview_type,
        interviewer_name=payload.interviewer_name,
        recruiter_name=payload.recruiter_name,
        recruiter_email=payload.recruiter_email,
        meeting_link=payload.meeting_link,
        meeting_id=payload.meeting_id,
        phone_number=payload.phone_number,
        access_pin=payload.access_pin,
        location=payload.location,
        notes=payload.notes,
    )

    update_status(db, analysis, AnalysisStatus.INTERVIEW)
    audit(db, request, "interview_upsert", f"id={analysis_id}")
    db.commit()

    return JSONResponse({"ok": True, "status": "colloquio"})


@router.get("/interviews/{analysis_id}")
def get_interview(
    analysis_id: str,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Return interview details for a given analysis."""
    validate_uuid(analysis_id)
    interview = get_interview_by_analysis(db, analysis_id)
    if not interview:
        return JSONResponse({"error": "No interview found"}, status_code=404)

    return JSONResponse(
        {
            "analysis_id": str(interview.analysis_id),
            "scheduled_at": interview.scheduled_at.isoformat(),
            "ends_at": interview.ends_at.isoformat() if interview.ends_at else None,
            "platform": interview.platform,
            "interview_type": interview.interview_type,
            "interviewer_name": interview.interviewer_name,
            "recruiter_name": interview.recruiter_name,
            "recruiter_email": interview.recruiter_email,
            "meeting_link": interview.meeting_link,
            "meeting_id": interview.meeting_id,
            "phone_number": interview.phone_number,
            "access_pin": interview.access_pin,
            "location": interview.location,
            "notes": interview.notes,
        }
    )


@router.delete("/interviews/{analysis_id}")
def remove_interview(
    request: Request,
    analysis_id: str,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Delete an interview and revert the analysis status to APPLIED."""
    validate_uuid(analysis_id)
    analysis = get_analysis_by_id(db, analysis_id)
    if not analysis:
        return JSONResponse({"error": "Analysis not found"}, status_code=404)

    deleted = delete_interview(db, str(analysis.id))
    if not deleted:
        return JSONResponse({"error": "No interview to delete"}, status_code=404)

    update_status(db, analysis, AnalysisStatus.APPLIED)
    audit(db, request, "interview_delete", f"id={analysis_id}")
    db.commit()

    return JSONResponse({"ok": True, "status": "candidato"})


class OutcomePayload(BaseModel):
    """Input schema for setting an interview round outcome."""

    outcome: str = Field(..., pattern=r"^(passed|rejected|withdrawn|pending)$")


class NextRoundPayload(BaseModel):
    """Input schema for appending a new interview round after a passed round."""

    scheduled_at: str
    interview_type: str | None = Field(None, max_length=20)


@router.post("/interviews/round/{interview_id}/outcome")
def set_round_outcome(
    request: Request,
    interview_id: str,
    payload: OutcomePayload,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Persist the outcome of a specific interview round.

    Side effects on the parent JobAnalysis.status:
    - ``rejected`` / ``withdrawn`` → move analysis to REJECTED (process ended).
    - ``passed`` / ``pending`` → no status change; caller must use
      ``/interviews/{analysis_id}/next-round`` to schedule the next step,
      or manually move the analysis to OFFER if this was the final round.
    """
    validate_uuid(interview_id)
    interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if not interview:
        return JSONResponse({"error": "Interview round not found"}, status_code=404)

    try:
        updated = set_outcome(db, interview_id, payload.outcome)
    except ValueError:
        # Pydantic already constrains `outcome` to the whitelist via the
        # regex pattern; set_outcome() re-validates defensively. A request
        # that slips past both is a bug, not user input — return a generic
        # 400 and keep the internal message off the wire.
        return JSONResponse({"error": "Invalid outcome value"}, status_code=400)

    if updated is None:
        return JSONResponse({"error": "Interview round not found"}, status_code=404)

    if payload.outcome in {InterviewOutcome.REJECTED.value, InterviewOutcome.WITHDRAWN.value}:
        analysis = get_analysis_by_id(db, str(updated.analysis_id))
        if analysis is not None:
            update_status(db, analysis, AnalysisStatus.REJECTED)

    audit(db, request, "interview_outcome", f"round={interview_id}, outcome={payload.outcome}")
    db.commit()
    return JSONResponse({"ok": True, "outcome": payload.outcome})


@router.post("/interviews/{analysis_id}/next-round")
def append_next_round(
    request: Request,
    analysis_id: str,
    payload: NextRoundPayload,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Append a new interview round to an analysis (e.g. after a passed round).

    Validates scheduled_at (same rules as upsert_interview) and ``interview_type``
    against the whitelist. Ensures the analysis status stays on INTERVIEW.
    """
    validate_uuid(analysis_id)
    analysis = get_analysis_by_id(db, analysis_id)
    if not analysis:
        return JSONResponse({"error": "Analysis not found"}, status_code=404)

    try:
        scheduled = datetime.fromisoformat(payload.scheduled_at)
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=UTC)
    except ValueError:
        return JSONResponse({"error": "Invalid scheduled_at format"}, status_code=400)

    if scheduled < datetime.now(UTC) - timedelta(hours=24):
        return JSONResponse({"error": "Non puoi prenotare un round nel passato"}, status_code=400)

    if payload.interview_type and payload.interview_type not in VALID_INTERVIEW_TYPES:
        return JSONResponse({"error": f"Tipo colloquio non valido: {payload.interview_type}"}, status_code=400)

    new_round = create_next_round(
        db,
        str(analysis.id),
        scheduled_at=scheduled,
        interview_type=payload.interview_type,
    )
    if new_round is None:
        return JSONResponse({"error": "Could not create round"}, status_code=500)

    update_status(db, analysis, AnalysisStatus.INTERVIEW)
    audit(
        db,
        request,
        "interview_next_round",
        f"analysis={analysis_id}, round={new_round.round_number}, type={payload.interview_type}",
    )
    db.commit()
    return JSONResponse(
        {
            "ok": True,
            "round_id": str(new_round.id),
            "round_number": new_round.round_number,
        }
    )


@router.get("/interviews-upcoming")
def upcoming_interviews(
    db: DbSession,
    user: CurrentUser,
    days: int | None = None,
) -> JSONResponse:
    """Return upcoming interviews within the specified timeframe."""
    return JSONResponse(get_upcoming_interviews(db, days=days))
