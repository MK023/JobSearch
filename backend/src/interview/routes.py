"""Interview JSON API routes."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..analysis.models import AnalysisStatus
from ..analysis.service import get_analysis_by_id, update_status
from ..audit.service import audit
from ..auth.models import User
from ..database import get_db
from ..dependencies import get_current_user
from .service import (
    create_or_update_interview,
    delete_interview,
    get_interview_by_analysis,
    get_upcoming_interviews,
)

router = APIRouter(tags=["interviews"])


class InterviewPayload(BaseModel):
    scheduled_at: str
    ends_at: str | None = None
    interview_type: str | None = Field(None, max_length=20)
    recruiter_name: str | None = Field(None, max_length=255)
    recruiter_email: str | None = Field(None, max_length=255)
    meeting_link: str | None = Field(None, max_length=500)
    phone_number: str | None = Field(None, max_length=50)
    phone_pin: str | None = Field(None, max_length=20)
    location: str | None = Field(None, max_length=500)
    notes: str | None = Field(None, max_length=2000)


@router.post("/interviews/{analysis_id}")
def upsert_interview(
    request: Request,
    analysis_id: str,
    payload: InterviewPayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    analysis = get_analysis_by_id(db, analysis_id)
    if not analysis:
        return JSONResponse({"error": "Analysis not found"}, status_code=404)

    try:
        scheduled = datetime.fromisoformat(payload.scheduled_at)
    except ValueError:
        return JSONResponse({"error": "Invalid scheduled_at format"}, status_code=400)

    # No scheduling far in the past (allow 24h buffer for timezone edge cases)
    if scheduled < datetime.now() - timedelta(hours=24):
        return JSONResponse({"error": "Non puoi prenotare un colloquio nel passato"}, status_code=400)

    ends = None
    if payload.ends_at:
        try:
            ends = datetime.fromisoformat(payload.ends_at)
        except ValueError:
            return JSONResponse({"error": "Invalid ends_at format"}, status_code=400)
        if ends <= scheduled:
            return JSONResponse({"error": "L'ora di fine deve essere dopo l'ora di inizio"}, status_code=400)

    create_or_update_interview(
        db,
        analysis.id,
        scheduled_at=scheduled,
        ends_at=ends,
        interview_type=payload.interview_type,
        recruiter_name=payload.recruiter_name,
        recruiter_email=payload.recruiter_email,
        meeting_link=payload.meeting_link,
        phone_number=payload.phone_number,
        phone_pin=payload.phone_pin,
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    interview = get_interview_by_analysis(db, analysis_id)
    if not interview:
        return JSONResponse({"error": "No interview found"}, status_code=404)

    return JSONResponse(
        {
            "analysis_id": str(interview.analysis_id),
            "scheduled_at": interview.scheduled_at.isoformat(),
            "ends_at": interview.ends_at.isoformat() if interview.ends_at else None,
            "interview_type": interview.interview_type,
            "recruiter_name": interview.recruiter_name,
            "recruiter_email": interview.recruiter_email,
            "meeting_link": interview.meeting_link,
            "phone_number": interview.phone_number,
            "phone_pin": interview.phone_pin,
            "location": interview.location,
            "notes": interview.notes,
        }
    )


@router.delete("/interviews/{analysis_id}")
def remove_interview(
    request: Request,
    analysis_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    analysis = get_analysis_by_id(db, analysis_id)
    if not analysis:
        return JSONResponse({"error": "Analysis not found"}, status_code=404)

    deleted = delete_interview(db, analysis.id)
    if not deleted:
        return JSONResponse({"error": "No interview to delete"}, status_code=404)

    # Revert status to APPLIED
    update_status(db, analysis, AnalysisStatus.APPLIED)
    audit(db, request, "interview_delete", f"id={analysis_id}")
    db.commit()

    return JSONResponse({"ok": True, "status": "candidato"})


@router.get("/interviews-upcoming")
def upcoming_interviews(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return JSONResponse(get_upcoming_interviews(db))
