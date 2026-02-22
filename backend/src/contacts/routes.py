"""Contact routes."""

from fastapi import APIRouter, Depends, Form
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..auth.models import User
from ..database import get_db
from ..dependencies import get_current_user
from .service import create_contact, delete_contact_by_id, get_contacts_for_analysis

router = APIRouter(tags=["contacts"])


@router.post("/contacts")
def add_contact(
    analysis_id: str = Form(""),
    name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    company: str = Form(""),
    linkedin_url: str = Form(""),
    notes: str = Form(""),
    source: str = Form("manual"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    contact = create_contact(db, analysis_id, name, email, phone, company, linkedin_url, notes, source)
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not delete_contact_by_id(db, contact_id):
        return JSONResponse({"error": "Contact not found"}, status_code=404)
    db.commit()
    return JSONResponse({"ok": True})
