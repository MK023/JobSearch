"""CV profile service — CRUD + retrieval del CV "attivo" per ogni utente.

Convenzione: ``get_latest_cv(db, user_id)`` ritorna l'ultimo CV
inserito; l'app è single-user single-CV per design, ma il modello
supporta più revisioni storiche (chi ha caricato una nuova CV vede
solo l'ultima nella UI, le vecchie restano per audit).

Il livello CEFR di inglese è normalizzato a write-time via
``normalize_cefr_token`` (A1..C2/Native, stringa vuota = non
dichiarato) — il DB tiene la stringa raw senza CHECK constraint per
non bloccare migrazioni di rows legacy.
"""

from uuid import UUID

from sqlalchemy.orm import Session

from ..integrations.validation import normalize_cefr_token
from .models import CVProfile


def get_latest_cv(db: Session, user_id: UUID) -> CVProfile | None:
    """Get the most recent CV for a user."""
    return db.query(CVProfile).filter(CVProfile.user_id == user_id).order_by(CVProfile.updated_at.desc()).first()


def save_cv(
    db: Session,
    user_id: UUID,
    raw_text: str,
    name: str = "",
    english_level: str = "",
) -> CVProfile:
    """Create or update the user's CV profile.

    ``english_level`` is normalized to one of "" / A1..C2 / Native via
    :func:`normalize_cefr_token`; tokens we cannot map (typos, free-text)
    silently degrade to "" — same graceful policy used on the AI side.
    """
    normalized_level = normalize_cefr_token(english_level)
    existing = db.query(CVProfile).filter(CVProfile.user_id == user_id).first()
    if existing:
        existing.raw_text = raw_text  # type: ignore[assignment]
        existing.name = name  # type: ignore[assignment]
        existing.english_level = normalized_level  # type: ignore[assignment]
    else:
        existing = CVProfile(
            user_id=user_id,
            raw_text=raw_text,
            name=name,
            english_level=normalized_level,
        )
        db.add(existing)
    db.flush()
    return existing
