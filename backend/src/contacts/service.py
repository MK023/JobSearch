"""Contact service — CRUD per i contatti recruiter / hiring manager.

Ogni ``Contact`` è opzionalmente legato a un'analisi (``analysis_id``
nullable): un recruiter può esistere senza un job specifico (lead di
network) e gli ``analysis`` con FK ``ON DELETE SET NULL`` preservano
lo storico contatti anche dopo la cancellazione di una JobAnalysis.

Out of scope: invio email, sync calendario, deduplica per email — sono
responsabilità rispettivamente di ``notifications``, ``interview``, e
del layer UI.
"""

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
    """Persist a new contact and return it (flushed, not committed)."""
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
    """Return all contacts linked to a given analysis, newest first."""
    uid = _to_uuid(analysis_id)
    if uid is None:
        return []
    return db.query(Contact).filter(Contact.analysis_id == uid).order_by(Contact.created_at.desc()).all()


def search_all_contacts(db: Session, query: str, limit: int = 20) -> list[Contact]:
    """Search all contacts by name, company, or email (case-insensitive)."""
    pattern = f"%{query}%"
    return (
        db.query(Contact)
        .filter((Contact.name.ilike(pattern)) | (Contact.company.ilike(pattern)) | (Contact.email.ilike(pattern)))
        .order_by(Contact.created_at.desc())
        .limit(min(limit, 50))
        .all()
    )


def delete_contact_by_id(db: Session, contact_id: str) -> bool:
    """Delete a contact by UUID string. Returns True if found and deleted."""
    uid = _to_uuid(contact_id)
    if uid is None:
        return False
    contact = db.query(Contact).filter(Contact.id == uid).first()
    if not contact:
        return False
    db.delete(contact)
    db.flush()
    return True
