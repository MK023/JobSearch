"""Contact routes."""

import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..config import settings
from ..dependencies import CurrentUser, DbSession, validate_uuid
from ..rate_limit import limiter
from .service import create_contact, delete_contact_by_id, get_contacts_for_analysis

router = APIRouter(tags=["contacts"])

VALID_SOURCES = {"manual", "linkedin", "email", "other"}
EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
URL_RE = re.compile(r"^https?://", re.IGNORECASE)


class ContactPayload(BaseModel):
    """Input schema for creating or updating a contact."""

    analysis_id: str = ""
    name: str = Field("", max_length=255)
    email: str = Field("", max_length=255)
    phone: str = Field("", max_length=50)
    company: str = Field("", max_length=255)
    linkedin_url: str = Field("", max_length=500)
    notes: str = Field("", max_length=2000)
    source: str = Field("manual", max_length=20)


@router.post("/contacts")
@limiter.limit(settings.rate_limit_default)
def add_contact(
    request: Request,
    payload: ContactPayload,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Create a new recruiter contact with validation."""
    if payload.source and payload.source not in VALID_SOURCES:
        return JSONResponse({"error": f"Source non valida: {payload.source}"}, status_code=400)
    if payload.email and not EMAIL_RE.match(payload.email):
        return JSONResponse({"error": "Formato email non valido"}, status_code=400)
    if payload.linkedin_url and not URL_RE.match(payload.linkedin_url):
        return JSONResponse({"error": "URL LinkedIn deve iniziare con http:// o https://"}, status_code=400)

    if payload.analysis_id:
        validate_uuid(payload.analysis_id)

    contact = create_contact(
        db,
        payload.analysis_id,
        payload.name,
        payload.email,
        payload.phone,
        payload.company,
        payload.linkedin_url,
        payload.notes,
        payload.source,
    )
    db.commit()
    return JSONResponse(
        {
            "ok": True,
            "contact": {
                "id": str(contact.id),
                "name": contact.name,
                "email": contact.email,
                "phone": contact.phone,
                "company": contact.company,
                "linkedin_url": contact.linkedin_url,
                "notes": contact.notes,
            },
        }
    )


@router.get("/contacts/{analysis_id}")
def list_contacts(
    analysis_id: str,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """List all contacts linked to a specific analysis."""
    validate_uuid(analysis_id)
    contacts = get_contacts_for_analysis(db, analysis_id)
    return JSONResponse(
        {
            "contacts": [
                {
                    "id": str(c.id),
                    "name": c.name,
                    "email": c.email,
                    "phone": c.phone,
                    "company": c.company,
                    "linkedin_url": c.linkedin_url,
                    "notes": c.notes,
                    "source": c.source,
                }
                for c in contacts
            ]
        }
    )


@router.delete("/contacts/{contact_id}")
def remove_contact(
    contact_id: str,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Delete a contact by ID."""
    validate_uuid(contact_id)
    if not delete_contact_by_id(db, contact_id):
        return JSONResponse({"error": "Contact not found"}, status_code=404)
    db.commit()
    return JSONResponse({"ok": True})
