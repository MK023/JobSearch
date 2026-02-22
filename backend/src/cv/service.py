"""CV profile service: CRUD operations."""

from uuid import UUID

from sqlalchemy.orm import Session

from .models import CVProfile


def get_latest_cv(db: Session, user_id: UUID) -> CVProfile | None:
    """Get the most recent CV for a user."""
    return db.query(CVProfile).filter(CVProfile.user_id == user_id).order_by(CVProfile.updated_at.desc()).first()


def save_cv(db: Session, user_id: UUID, raw_text: str, name: str = "") -> CVProfile:
    """Create or update the user's CV profile."""
    existing = db.query(CVProfile).filter(CVProfile.user_id == user_id).first()
    if existing:
        existing.raw_text = raw_text
        existing.name = name
    else:
        existing = CVProfile(user_id=user_id, raw_text=raw_text, name=name)
        db.add(existing)
    db.flush()
    return existing
