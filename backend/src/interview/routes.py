"""Interview JSON API routes."""

import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..analysis.models import AnalysisStatus
from ..analysis.service import get_analysis_by_id, update_status
from ..audit.service import audit
from ..dependencies import CurrentUser, DbSession
from .service import (
    create_or_update_interview,
    delete_interview,
    get_interview_by_analysis,
    get_upcoming_interviews,
)

router = APIRouter(tags=["interviews"])


VALID_PLATFORMS = {"google_meet", "teams", "zoom", "phone", "in_person", "other"}
VALID_INTERVIEW_TYPES = {"tecnico", "hr", "conoscitivo", "finale", "other"}
EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
URL_RE = re.compile(r"^https?://", re.IGNORECASE)


class InterviewPayload(BaseModel):
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
    analysis = get_analysis_by_id(db, analysis_id)
    if not analysis:
        return JSONResponse({"error": "Analysis not found"}, status_code=404)

    try:
        scheduled = datetime.fromisoformat(payload.scheduled_at)
    except ValueError:
        return JSONResponse({"error": "Invalid scheduled_at format"}, status_code=400)

    # No scheduling far in the past (allow 24h buffer for timezone edge cases)
    if scheduled < datetime.now(UTC) - timedelta(hours=24):
        return JSONResponse({"error": "Non puoi prenotare un colloquio nel passato"}, status_code=400)

    ends = None
    if payload.ends_at:
        try:
            ends = datetime.fromisoformat(payload.ends_at)
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

    # Also set status to INTERVIEW
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
    analysis = get_analysis_by_id(db, analysis_id)
    if not analysis:
        return JSONResponse({"error": "Analysis not found"}, status_code=404)

    deleted = delete_interview(db, str(analysis.id))
    if not deleted:
        return JSONResponse({"error": "No interview to delete"}, status_code=404)

    # Revert status to APPLIED
    update_status(db, analysis, AnalysisStatus.APPLIED)
    audit(db, request, "interview_delete", f"id={analysis_id}")
    db.commit()

    return JSONResponse({"ok": True, "status": "candidato"})


@router.get("/interviews-upcoming")
def upcoming_interviews(
    db: DbSession,
    user: CurrentUser,
    days: int | None = None,
) -> JSONResponse:
    return JSONResponse(get_upcoming_interviews(db, days=days))
