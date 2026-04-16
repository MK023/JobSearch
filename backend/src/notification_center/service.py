"""Aggregator: read current app state and produce a list of Notification.

Each rule is isolated in a small helper. Helpers return ``[]`` when the
rule does not fire. ``get_notifications`` concatenates and sorts by
severity (critical first) then by created_at (newest first).

Rules:
1. INTERVIEW_UPCOMING (critical) — an interview is scheduled within the
   next 24h. One notification per interview.
2. BUDGET_LOW (critical if <$0.50, warning if <$1) — Anthropic remaining
   credit has dropped below the threshold. One notification, never
   duplicated.
3. INTERVIEW_NO_OUTCOME (warning) — an interview round is >3 days in
   the past and its ``outcome`` is still NULL. One per interview.
4. DB_SIZE_HIGH (warning) — database usage is >80% of the 1GB Neon
   free-tier limit. One notification, never duplicated.
5. FOLLOWUP_DUE (info, dismissible) — application sent >N days ago and
   not yet followed up. One per analysis.
6. BACKLOG_TO_REVIEW (info, dismissible) — more than 10 PENDING
   analyses. One notification, never duplicated.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..analysis.models import AnalysisStatus, JobAnalysis
from ..dashboard.service import get_followup_alerts, get_spending
from ..interview.models import Interview
from ..interview.service import get_upcoming_interviews
from .models import Notification, NotificationDismissal, NotificationSeverity, NotificationType

# Thresholds — tuned to Marco's setup (Neon free 1GB, Anthropic pay-as-you-go).
_INTERVIEW_UPCOMING_HOURS = 24
_INTERVIEW_NO_OUTCOME_DAYS = 3
_BUDGET_WARNING = 1.00
_BUDGET_CRITICAL = 0.50
_DB_SIZE_WARNING_MB = 800  # 80% of 1GB Neon free tier
_BACKLOG_THRESHOLD = 1


def _upcoming_interviews(db: Session) -> list[Notification]:
    rows = get_upcoming_interviews(db, hours=_INTERVIEW_UPCOMING_HOURS)
    return [
        Notification(
            id=f"interview:{row['analysis_id']}",
            type=NotificationType.INTERVIEW_UPCOMING,
            severity=NotificationSeverity.CRITICAL,
            title=f"Colloquio in arrivo — {row['company']}",
            body=f"{row['role']} · {row['date_display']} {row['time_display']}",
            action_url=f"/analysis/{row['analysis_id']}",
            action_label="Apri dettaglio",
            dismissible=True,
            sticky=True,
            created_at=datetime.fromisoformat(row["scheduled_at"]),
        )
        for row in rows
    ]


def _low_budget(db: Session) -> list[Notification]:
    spending = get_spending(db)
    remaining = spending.get("remaining")
    if remaining is None or remaining >= _BUDGET_WARNING:
        return []
    severity = NotificationSeverity.CRITICAL if remaining < _BUDGET_CRITICAL else NotificationSeverity.WARNING
    return [
        Notification(
            id="budget:anthropic",
            type=NotificationType.BUDGET_LOW,
            severity=severity,
            title=f"Credito Anthropic basso — ${remaining:.2f}",
            body=("Ricarica prima che si esaurisca: analisi e cover letter fallirebbero in mezzo a un invio."),
            action_url="https://console.anthropic.com/settings/billing",
            action_label="Ricarica",
            dismissible=True,
            sticky=True,
            created_at=datetime.now(UTC),
        )
    ]


def _interviews_without_outcome(db: Session) -> list[Notification]:
    cutoff = datetime.now(UTC) - timedelta(days=_INTERVIEW_NO_OUTCOME_DAYS)
    rows = (
        db.query(Interview, JobAnalysis)
        .join(JobAnalysis, Interview.analysis_id == JobAnalysis.id)
        .filter(
            Interview.scheduled_at < cutoff,
            Interview.outcome.is_(None),
            JobAnalysis.status.in_([AnalysisStatus.INTERVIEW.value, AnalysisStatus.OFFER.value]),
        )
        .order_by(Interview.scheduled_at.desc())
        .all()
    )
    out: list[Notification] = []
    for interview, analysis in rows:
        scheduled: datetime = interview.scheduled_at
        out.append(
            Notification(
                id=f"interview_outcome:{interview.id}",
                type=NotificationType.INTERVIEW_NO_OUTCOME,
                severity=NotificationSeverity.WARNING,
                title=f"Esito colloquio — {analysis.company}",
                body=(
                    f"{analysis.role} · round {interview.round_number} del "
                    f"{scheduled.strftime('%d/%m/%Y')}. "
                    "Logga l'esito per non perdere il funnel."
                ),
                action_url=f"/analysis/{analysis.id}",
                action_label="Logga esito",
                dismissible=True,
                sticky=True,
                created_at=scheduled,
            )
        )
    return out


def _db_size_high(db: Session) -> list[Notification]:
    size_mb = _db_size_mb(db)
    if size_mb is None or size_mb < _DB_SIZE_WARNING_MB:
        return []
    return [
        Notification(
            id="db:size",
            type=NotificationType.DB_SIZE_HIGH,
            severity=NotificationSeverity.WARNING,
            title=f"Database quasi pieno — {size_mb:.0f} MB su 1024 MB",
            body=("Neon free tier ha un limite di 1 GB. Esegui cleanup delle analisi vecchie dalla sezione Settings."),
            action_url="/settings",
            action_label="Apri Settings",
            dismissible=True,
            sticky=True,
            created_at=datetime.now(UTC),
        )
    ]


def _db_size_mb(db: Session) -> float | None:
    """Return the current database size in MB, or None if unsupported (SQLite)."""
    try:
        result = db.execute(func.pg_database_size(func.current_database())).scalar()
    except Exception:
        return None
    if result is None:
        return None
    return float(result) / (1024 * 1024)


def _followup_due(db: Session) -> list[Notification]:
    alerts = get_followup_alerts(db)
    out: list[Notification] = []
    now = datetime.now(UTC)
    for a in alerts:
        applied: datetime | None = a.applied_at  # type: ignore[assignment]
        out.append(
            Notification(
                id=f"followup:{a.id}",
                type=NotificationType.FOLLOWUP_DUE,
                severity=NotificationSeverity.INFO,
                title=f"Follow-up suggerito — {a.company}",
                body=(
                    f"{a.role} · candidatura inviata il "
                    f"{applied.strftime('%d/%m/%Y') if applied else 'data non nota'}. "
                    "Valuta se mandare un remind al recruiter."
                ),
                action_url=f"/analysis/{a.id}",
                action_label="Apri",
                dismissible=True,
                sticky=False,
                created_at=applied or now,
            )
        )
    return out


def _backlog_to_review(db: Session) -> list[Notification]:
    count = (
        db.query(func.count(JobAnalysis.id)).filter(JobAnalysis.status == AnalysisStatus.PENDING.value).scalar() or 0
    )
    if count < _BACKLOG_THRESHOLD:
        return []
    return [
        Notification(
            id=f"backlog:da_valutare:{count}",
            type=NotificationType.BACKLOG_TO_REVIEW,
            severity=NotificationSeverity.WARNING,
            title=f"{count} analisi da valutare (Cowork)",
            body="Nuovi risultati da Cowork pronti per la revisione.",
            action_url="/history",
            action_label="Apri Storico",
            dismissible=True,
            sticky=False,
            created_at=datetime.now(UTC),
        )
    ]


_SEVERITY_ORDER = {
    NotificationSeverity.CRITICAL: 0,
    NotificationSeverity.WARNING: 1,
    NotificationSeverity.INFO: 2,
}


def _get_dismissed_ids(db: Session) -> set[str]:
    """Return the set of notification IDs the user has dismissed."""
    rows = db.query(NotificationDismissal.notification_id).all()
    return {r[0] for r in rows}


def get_notifications(db: Session) -> list[Notification]:
    """Return the notification list sorted by severity, then recency.

    Dismissed notifications are excluded — the sidebar badge and the
    page count both see the same filtered list.
    """
    dismissed = _get_dismissed_ids(db)

    out: list[Notification] = []
    out.extend(_upcoming_interviews(db))
    out.extend(_low_budget(db))
    out.extend(_interviews_without_outcome(db))
    out.extend(_db_size_high(db))
    out.extend(_followup_due(db))
    out.extend(_backlog_to_review(db))

    out = [n for n in out if n.id not in dismissed]
    out.sort(key=lambda n: (_SEVERITY_ORDER[n.severity], -n.created_at.timestamp()))
    return out


def get_unread_count(db: Session) -> int:
    """Badge count for the sidebar — matches the visible notification list."""
    return len(get_notifications(db))


def dismiss_notification(db: Session, notification_id: str) -> bool:
    """Dismiss a notification. Returns True if newly dismissed, False if already was."""
    existing = db.query(NotificationDismissal).filter(NotificationDismissal.notification_id == notification_id).first()
    if existing:
        return False
    db.add(NotificationDismissal(notification_id=notification_id))
    db.flush()
    return True


def undismiss_notification(db: Session, notification_id: str) -> bool:
    """Restore a dismissed notification. Returns True if found and removed."""
    row = db.query(NotificationDismissal).filter(NotificationDismissal.notification_id == notification_id).first()
    if not row:
        return False
    db.delete(row)
    db.flush()
    return True


# Re-export the reusable DB size helper so /health can share the code.
db_size_mb = _db_size_mb
__all__ = [
    "get_notifications",
    "get_unread_count",
    "dismiss_notification",
    "undismiss_notification",
    "db_size_mb",
]
