"""Notification utilities: credential encryption and deduplication checks."""

import base64
import hashlib
import uuid

from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from ..config import settings
from .models import NotificationLog


def _derive_fernet_key(secret: str) -> bytes:
    """Derive a Fernet key from the app SECRET_KEY using SHA-256."""
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_value(plaintext: str) -> str:
    """Encrypt a string value using the app's SECRET_KEY."""
    f = Fernet(_derive_fernet_key(settings.secret_key))
    return f.encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    """Decrypt a string value using the app's SECRET_KEY."""
    f = Fernet(_derive_fernet_key(settings.secret_key))
    return f.decrypt(ciphertext.encode()).decode()


def _already_notified(db: Session, analysis_id: uuid.UUID, notification_type: str) -> bool:
    """Check if a notification of this type was already sent for this analysis."""
    return (
        db.query(NotificationLog)
        .filter(
            NotificationLog.analysis_id == analysis_id,
            NotificationLog.notification_type == notification_type,
        )
        .first()
        is not None
    )
