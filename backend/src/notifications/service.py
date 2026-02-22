"""Email notification service with encrypted SMTP credentials.

Sends follow-up reminder emails when applications are older than N days.
SMTP password is stored encrypted using Fernet (AES-128-CBC) derived from SECRET_KEY.
"""

import base64
import hashlib
import logging
import smtplib
import uuid
from datetime import UTC, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid
from html import escape

from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from ..analysis.models import AnalysisStatus, JobAnalysis
from ..config import settings
from .models import NotificationLog

logger = logging.getLogger(__name__)

_SENDER_NAME = "JobSearch Command Center"


# ── Credential encryption ─────────────────────────────────────────────


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


# ── Email building ─────────────────────────────────────────────────────


def _build_followup_email(analysis: JobAnalysis, days_since: int) -> MIMEMultipart:
    """Build a follow-up reminder email with proper anti-spam headers."""
    msg = MIMEMultipart("alternative")

    # ── Anti-spam headers ──
    from_addr = formataddr((_SENDER_NAME, settings.smtp_user))
    msg["From"] = from_addr
    msg["To"] = settings.notification_email
    msg["Reply-To"] = settings.smtp_user
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=settings.smtp_user.split("@")[-1] if "@" in settings.smtp_user else "local")
    msg["X-Mailer"] = "JobSearch/2.0"
    msg["Subject"] = f"Sollecito candidatura: {analysis.role} presso {analysis.company}"

    # ── Escape dynamic data for HTML ──
    role = escape(analysis.role or "")
    company = escape(analysis.company or "")
    status_val = escape(analysis.status.value if analysis.status else "n/d")
    score = analysis.score or 0

    # ── Plain text (multipart/alternative - kept for spam score) ──
    text_body = (
        f"Promemoria Follow-up - JobSearch Command Center\n"
        f"{'=' * 48}\n\n"
        f"Sono passati {days_since} giorni dalla candidatura per il ruolo\n"
        f"di {analysis.role} presso {analysis.company}.\n\n"
        f"  Ruolo:    {analysis.role}\n"
        f"  Azienda:  {analysis.company}\n"
        f"  Score:    {score}/100\n"
        f"  Stato:    {status_val}\n\n"
        f"Considera di inviare un follow-up al recruiter per\n"
        f"dimostrare interesse e chiedere aggiornamenti.\n\n"
        f"--\n"
        f"JobSearch Command Center\n"
        f"Questo messaggio e' stato inviato automaticamente.\n"
    )

    # ── HTML (proper DOCTYPE, inline styles for email clients) ──
    html_body = f"""\
<!DOCTYPE html>
<html lang="it" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Promemoria Follow-up</title>
</head>
<body style="margin:0; padding:0; background-color:#f4f4f5; font-family:Calibri,Arial,Helvetica,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f4f5;">
    <tr><td align="center" style="padding:24px 16px;">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0"
             style="background-color:#ffffff; border-radius:8px; box-shadow:0 1px 3px rgba(0,0,0,0.1);">
        <!-- Header -->
        <tr><td style="background-color:#1e40af; padding:20px 32px; border-radius:8px 8px 0 0;">
          <h1 style="margin:0; color:#ffffff; font-size:20px; font-weight:600;">
            Promemoria Follow-up
          </h1>
        </td></tr>
        <!-- Body -->
        <tr><td style="padding:32px;">
          <p style="margin:0 0 16px; color:#374151; font-size:15px; line-height:1.6;">
            Sono passati <strong style="color:#1e40af;">{days_since} giorni</strong>
            dalla tua candidatura. Potrebbe essere il momento giusto per un follow-up.
          </p>
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                 style="background-color:#f9fafb; border-radius:6px; margin:16px 0;">
            <tr><td style="padding:16px 20px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td style="padding:6px 0; color:#6b7280; font-size:13px; width:90px;">Ruolo</td>
                  <td style="padding:6px 0; color:#111827; font-size:14px; font-weight:600;">{role}</td>
                </tr>
                <tr>
                  <td style="padding:6px 0; color:#6b7280; font-size:13px;">Azienda</td>
                  <td style="padding:6px 0; color:#111827; font-size:14px; font-weight:600;">{company}</td>
                </tr>
                <tr>
                  <td style="padding:6px 0; color:#6b7280; font-size:13px;">Score</td>
                  <td style="padding:6px 0; color:#111827; font-size:14px; font-weight:600;">{score}/100</td>
                </tr>
                <tr>
                  <td style="padding:6px 0; color:#6b7280; font-size:13px;">Stato</td>
                  <td style="padding:6px 0; color:#111827; font-size:14px;">{status_val}</td>
                </tr>
              </table>
            </td></tr>
          </table>
          <p style="margin:16px 0 0; color:#374151; font-size:14px; line-height:1.6;">
            Un breve messaggio al recruiter dimostra interesse e professionalit&agrave;.
          </p>
        </td></tr>
        <!-- Footer -->
        <tr><td style="padding:16px 32px; border-top:1px solid #e5e7eb;">
          <p style="margin:0; color:#9ca3af; font-size:11px; line-height:1.5;">
            Inviato automaticamente da JobSearch Command Center.<br>
            Questa notifica viene inviata una sola volta per candidatura.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg


# ── Email sending ──────────────────────────────────────────────────────


def _send_email(msg: MIMEMultipart) -> bool:
    """Send an email via SMTP with TLS. Returns True on success."""
    if not settings.smtp_user or not settings.smtp_password:
        logger.debug("SMTP not configured, skipping email send")
        return False

    try:
        # Decrypt password if it looks encrypted (Fernet tokens start with 'gAAAAA')
        password = settings.smtp_password
        if password.startswith("gAAAAA"):
            password = decrypt_value(password)

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(settings.smtp_user, password)
            server.send_message(msg)
        return True
    except Exception:
        logger.exception("Failed to send email notification")
        return False


def _already_notified(db: Session, analysis_id: uuid.UUID, notification_type: str) -> bool:
    """Check if we already sent this notification type for this analysis."""
    return (
        db.query(NotificationLog)
        .filter(
            NotificationLog.analysis_id == analysis_id,
            NotificationLog.notification_type == notification_type,
        )
        .first()
        is not None
    )


# ── Main check & send ─────────────────────────────────────────────────


def check_and_send_followup_reminders(db: Session) -> int:
    """Check for applications needing follow-up and send email reminders.

    Called during dashboard load or via a scheduled task.
    Returns the number of emails sent.
    """
    if not settings.smtp_user or not settings.notification_email:
        return 0

    threshold = datetime.now(UTC) - timedelta(days=settings.followup_reminder_days)

    analyses = (
        db.query(JobAnalysis)
        .filter(
            JobAnalysis.status.in_([AnalysisStatus.APPLIED, AnalysisStatus.INTERVIEW]),
            JobAnalysis.applied_at.isnot(None),
            JobAnalysis.applied_at <= threshold,
            JobAnalysis.followed_up == False,  # noqa: E712
        )
        .order_by(JobAnalysis.applied_at.asc())
        .all()
    )

    sent_count = 0
    for analysis in analyses:
        if _already_notified(db, analysis.id, "followup_reminder"):
            continue

        days_since = (datetime.now(UTC) - analysis.applied_at).days
        msg = _build_followup_email(analysis, days_since)

        if _send_email(msg):
            db.add(
                NotificationLog(
                    analysis_id=analysis.id,
                    notification_type="followup_reminder",
                    recipient=settings.notification_email,
                    subject=msg["Subject"],
                    detail=f"{analysis.role} @ {analysis.company}, {days_since}gg",
                )
            )
            sent_count += 1
            logger.info(
                "Sent followup reminder for %s @ %s (%d days)",
                analysis.role,
                analysis.company,
                days_since,
            )

    if sent_count > 0:
        db.flush()

    return sent_count
