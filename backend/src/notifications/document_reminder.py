"""Document reminder service using Resend API.

Sends email reminders when uploaded documents are flagged as not_compiled
by the Claude API scanner. Uses Resend free tier (100 emails/day).
"""

import logging
from html import escape
from typing import cast
from uuid import UUID

import resend
from sqlalchemy.orm import Session

from ..analysis.models import JobAnalysis
from ..config import settings
from ..interview.file_models import InterviewFile
from ..interview.file_service import get_not_compiled_files
from ..interview.models import Interview
from .models import NotificationLog

logger = logging.getLogger(__name__)


def _build_document_reminder_html(
    files: list[InterviewFile],
    company: str,
    role: str,
) -> str:
    """Build HTML email for unfilled document reminder."""
    company_esc = escape(company)
    role_esc = escape(role)

    file_rows = ""
    for f in files:
        fname = escape(str(f.original_filename))
        scan_text = escape(str(f.scan_result or "Non compilato"))
        file_rows += (
            "<tr>"
            f'<td style="padding:8px 12px; border-bottom:1px solid #e5e7eb; color:#111827; font-size:14px;">{fname}</td>'
            f'<td style="padding:8px 12px; border-bottom:1px solid #e5e7eb; color:#dc2626; font-size:13px;">{scan_text}</td>'
            "</tr>"
        )

    return (
        "<!DOCTYPE html>"
        '<html lang="it" xmlns="http://www.w3.org/1999/xhtml">'
        "<head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        "<title>Documenti da compilare</title>"
        "</head>"
        '<body style="margin:0; padding:0; background-color:#f4f4f5; font-family:Calibri,Arial,Helvetica,sans-serif;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f4f5;">'
        '<tr><td align="center" style="padding:24px 16px;">'
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0"'
        ' style="background-color:#ffffff; border-radius:8px; box-shadow:0 1px 3px rgba(0,0,0,0.1);">'
        '<tr><td style="background-color:#dc2626; padding:20px 32px; border-radius:8px 8px 0 0;">'
        '<h1 style="margin:0; color:#ffffff; font-size:20px; font-weight:600;">'
        "Documenti da compilare"
        "</h1></td></tr>"
        '<tr><td style="padding:32px;">'
        '<p style="margin:0 0 16px; color:#374151; font-size:15px; line-height:1.6;">'
        "I seguenti documenti per la candidatura "
        f"<strong>{role_esc}</strong> presso <strong>{company_esc}</strong> "
        "risultano non compilati:"
        "</p>"
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"'
        ' style="border:1px solid #e5e7eb; border-radius:6px; margin:16px 0;">'
        "<tr>"
        '<th style="padding:10px 12px; background-color:#f9fafb; text-align:left; color:#6b7280;'
        ' font-size:12px; text-transform:uppercase;">File</th>'
        '<th style="padding:10px 12px; background-color:#f9fafb; text-align:left; color:#6b7280;'
        ' font-size:12px; text-transform:uppercase;">Stato</th>'
        "</tr>"
        f"{file_rows}"
        "</table>"
        '<p style="margin:16px 0 0; color:#374151; font-size:14px; line-height:1.6;">'
        "Compila i documenti e ricaricali prima del colloquio."
        "</p>"
        "</td></tr>"
        '<tr><td style="padding:16px 32px; border-top:1px solid #e5e7eb;">'
        '<p style="margin:0; color:#9ca3af; font-size:11px; line-height:1.5;">'
        "Inviato automaticamente da JobSearch Command Center.<br>"
        "Questa notifica viene inviata una sola volta per documento."
        "</p></td></tr>"
        "</table>"
        "</td></tr></table>"
        "</body></html>"
    )


def _build_plain_text(
    files: list[InterviewFile],
    company: str,
    role: str,
) -> str:
    """Build plain text version of the reminder."""
    lines = [
        f"Documenti da compilare - {role} @ {company}",
        "=" * 48,
        "",
        "I seguenti documenti risultano non compilati:",
        "",
    ]
    for f in files:
        lines.append(f"  - {f.original_filename}: {f.scan_result or 'Non compilato'}")
    lines.extend(
        [
            "",
            "Compila i documenti e ricaricali prima del colloquio.",
            "",
            "--",
            "JobSearch Command Center",
        ]
    )
    return "\n".join(lines)


def _group_files_by_interview(files: list[InterviewFile]) -> dict[str, list[InterviewFile]]:
    """Group not-compiled files by their interview_id."""
    grouped: dict[str, list[InterviewFile]] = {}
    for f in files:
        grouped.setdefault(str(f.interview_id), []).append(f)
    return grouped


def _preload_already_notified(db: Session, files_by_interview: dict[str, list[InterviewFile]]) -> set[str]:
    """Preload all already-notified file IDs across all interviews in ONE query.

    Previous code issued one SELECT per file inside the interview loop (N+1).
    """
    all_file_ids = [str(f.id) for files in files_by_interview.values() for f in files]
    if not all_file_ids:
        return set()
    notif_types = [f"document_reminder:{fid}" for fid in all_file_ids]
    rows = db.query(NotificationLog.notification_type).filter(NotificationLog.notification_type.in_(notif_types)).all()
    return {row[0].split(":", 1)[1] for row in rows if ":" in row[0]}


def _log_reminders_sent(
    db: Session,
    analysis_id: UUID,
    files: list[InterviewFile],
    subject: str,
) -> None:
    """Persist one NotificationLog per file just emailed, to dedupe future runs."""
    for f in files:
        db.add(
            NotificationLog(
                analysis_id=analysis_id,
                notification_type=f"document_reminder:{f.id}",
                recipient=settings.document_reminder_email,
                subject=subject,
                detail=f"{f.original_filename} - {f.scan_result or 'non compilato'}",
            )
        )


def _process_interview_reminder(
    db: Session,
    interview_id: str,
    files: list[InterviewFile],
    already_sent_all: set[str],
) -> bool:
    """Send a reminder email for a single interview and log the outcome.

    Returns True if an email was actually sent, False otherwise (skipped/failed).
    """
    new_files = [f for f in files if str(f.id) not in already_sent_all]
    if not new_files:
        return False

    interview = db.query(Interview).filter(Interview.id == UUID(interview_id)).first()
    if not interview:
        return False
    analysis = db.query(JobAnalysis).filter(JobAnalysis.id == interview.analysis_id).first()
    if not analysis:
        return False

    company = str(analysis.company or "N/D")
    role = str(analysis.role or "N/D")
    subject = f"Documenti da compilare: {role} @ {company}"

    html = _build_document_reminder_html(new_files, company, role)
    text = _build_plain_text(new_files, company, role)

    try:
        resend.Emails.send(
            {
                "from": f"JobSearch <{settings.resend_from_email}>",
                "to": [settings.document_reminder_email],
                "subject": subject,
                "html": html,
                "text": text,
            }
        )
    except Exception:
        logger.exception("Failed to send document reminder for interview %s", interview_id)
        return False

    _log_reminders_sent(db, cast(UUID, analysis.id), new_files, subject)
    logger.info(
        "Sent document reminder for %s @ %s (%d files)",
        role,
        company,
        len(new_files),
    )
    return True


def send_document_reminders(db: Session) -> int:
    """Check for not_compiled files and send reminder emails.

    Groups files by interview/analysis for a single email per interview.
    Uses Resend API instead of SMTP.

    Returns:
        Number of emails sent.
    """
    if not settings.resend_api_key or not settings.document_reminder_email:
        logger.debug("Resend not configured, skipping document reminders")
        return 0

    resend.api_key = settings.resend_api_key

    not_compiled_files = get_not_compiled_files(db)
    if not not_compiled_files:
        return 0

    files_by_interview = _group_files_by_interview(not_compiled_files)
    already_sent_all = _preload_already_notified(db, files_by_interview)

    sent_count = sum(
        1
        for interview_id, files in files_by_interview.items()
        if _process_interview_reminder(db, interview_id, files, already_sent_all)
    )

    if sent_count > 0:
        db.flush()

    return sent_count
