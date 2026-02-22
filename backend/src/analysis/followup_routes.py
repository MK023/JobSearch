"""Follow-up email and LinkedIn message routes."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..audit.service import audit
from ..auth.models import User
from ..contacts.models import Contact
from ..cv.service import get_latest_cv
from ..dashboard.service import add_spending
from ..database import get_db
from ..dependencies import get_current_user
from ..integrations.anthropic_client import generate_followup_email, generate_linkedin_message
from .service import get_analysis_by_id

router = APIRouter(tags=["followup"])


@router.post("/followup-email")
def create_followup_email(
    request: Request,
    analysis_id: str = Form(...),
    language: str = Form("italiano"),
    model: str = Form("haiku"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    analysis = get_analysis_by_id(db, analysis_id)
    if not analysis:
        return JSONResponse({"error": "Analysis not found"}, status_code=404)

    cv = get_latest_cv(db, user.id)
    if not cv:
        return JSONResponse({"error": "CV not found"}, status_code=404)

    days_since = (datetime.now(UTC) - analysis.applied_at).days if analysis.applied_at else 7

    try:
        result = generate_followup_email(cv.raw_text, analysis.role, analysis.company, days_since, language, model)
    except Exception as exc:
        audit(db, request, "followup_email_error", str(exc))
        db.commit()
        return JSONResponse({"error": str(exc)}, status_code=500)

    add_spending(
        db,
        result.get("cost_usd", 0.0),
        result.get("tokens", {}).get("input", 0),
        result.get("tokens", {}).get("output", 0),
        is_analysis=False,
    )
    audit(db, request, "followup_email", f"analysis={analysis_id}, company={analysis.company}")
    db.commit()
    return JSONResponse({"ok": True, **result})


@router.post("/linkedin-message")
def create_linkedin_message(
    request: Request,
    analysis_id: str = Form(...),
    language: str = Form("italiano"),
    model: str = Form("haiku"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    analysis = get_analysis_by_id(db, analysis_id)
    if not analysis:
        return JSONResponse({"error": "Analysis not found"}, status_code=404)

    cv = get_latest_cv(db, user.id)
    if not cv:
        return JSONResponse({"error": "CV not found"}, status_code=404)

    contact = db.query(Contact).filter(Contact.analysis_id == analysis.id).first()
    contact_info = ""
    if contact:
        parts = []
        if contact.name:
            parts.append(f"Nome: {contact.name}")
        if contact.linkedin_url:
            parts.append(f"LinkedIn: {contact.linkedin_url}")
        contact_info = ", ".join(parts)

    try:
        result = generate_linkedin_message(cv.raw_text, analysis.role, analysis.company, contact_info, language, model)
    except Exception as exc:
        audit(db, request, "linkedin_msg_error", str(exc))
        db.commit()
        return JSONResponse({"error": str(exc)}, status_code=500)

    add_spending(
        db,
        result.get("cost_usd", 0.0),
        result.get("tokens", {}).get("input", 0),
        result.get("tokens", {}).get("output", 0),
        is_analysis=False,
    )
    audit(db, request, "linkedin_message", f"analysis={analysis_id}, company={analysis.company}")
    db.commit()
    return JSONResponse({"ok": True, **result})


@router.post("/followup-done/{analysis_id}")
def mark_followup_done(
    request: Request,
    analysis_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    analysis = get_analysis_by_id(db, analysis_id)
    if not analysis:
        return JSONResponse({"error": "Analysis not found"}, status_code=404)
    analysis.followed_up = True
    audit(db, request, "followup_done", f"analysis={analysis_id}")
    db.commit()
    return JSONResponse({"ok": True})
