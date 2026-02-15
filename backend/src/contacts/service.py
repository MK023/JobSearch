"""Contact service: CRUD for recruiter contacts."""

from uuid import UUID

from sqlalchemy.orm import Session

from .models import Contact


def _to_uuid(value: str) -> UUID | None:
    """Convert string to UUID, returning None on failure."""
    if not value:
        return None
    try:
        return UUID(value)
    except (ValueError, AttributeError):
        return None


def create_contact(
    db: Session,
    analysis_id: str | None,
    name: str,
    email: str,
    phone: str,
    company: str,
    linkedin_url: str,
    notes: str,
    source: str = "manual",
) -> Contact:
    contact = Contact(
        analysis_id=_to_uuid(analysis_id) if analysis_id else None,
        name=name,
        email=email,
        phone=phone,
        company=company,
        linkedin_url=linkedin_url,
        notes=notes,
        source=source,
    )
    db.add(contact)
    db.flush()
    return contact


def get_contacts_for_analysis(db: Session, analysis_id: str) -> list[Contact]:
    uid = _to_uuid(analysis_id)
    if uid is None:
        return []
    return (
        db.query(Contact)
        .filter(Contact.analysis_id == uid)
        .order_by(Contact.created_at.desc())
        .all()
    )


def delete_contact_by_id(db: Session, contact_id: str) -> bool:
    uid = _to_uuid(contact_id)
    if uid is None:
        return False
    contact = db.query(Contact).filter(Contact.id == uid).first()
    if not contact:
        return False
    db.delete(contact)
    db.flush()
    return True
