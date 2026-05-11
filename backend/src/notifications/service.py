"""Notification log utilities — encryption + dedup contro spam in invio.

Coppia di responsabilità:

- **Encryption Fernet** (``encrypt_credential`` / ``decrypt_credential``)
  per le credenziali SMTP o token recruiter salvati su DB. La chiave è
  derivata da ``settings.secret_key`` (SHA256 + base64 urlsafe), così
  un dump del DB rubato non espone credenziali in chiaro.
- **Dedup** (``check_already_sent``) interroga ``notification_logs`` per
  ``(analysis_id, notification_type)`` — evita follow-up duplicati se
  l'utente ricarica la pagina prima del refresh del badge.

Out of scope: invio email vero (Resend SDK), template HTML — vivono in
``notifications/email_sender`` e nei template Jinja.
"""

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
