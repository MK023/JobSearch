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
from ..preferences.service import get_preference
from .models import Notification, NotificationDismissal, NotificationSeverity, NotificationType

# Default thresholds — overridable via Settings > Parametri operativi.
_INTERVIEW_UPCOMING_HOURS = 24
_INTERVIEW_NO_OUTCOME_DAYS_DEFAULT = 3
_BUDGET_WARNING_DEFAULT = 1.00
_BUDGET_CRITICAL_DEFAULT = 0.50
_DB_SIZE_WARNING_MB = 800  # 80% of 1GB Neon free tier
_BACKLOG_THRESHOLD = 1


def _thresholds(db: Session) -> dict[str, float]:
    """Load notification thresholds from preferences (with hardcoded defaults)."""
    return {
        "interview_no_outcome_days": int(
            get_preference(db, "interview_no_outcome_days", _INTERVIEW_NO_OUTCOME_DAYS_DEFAULT)
        ),
        "budget_warning": float(get_preference(db, "budget_warning_threshold", _BUDGET_WARNING_DEFAULT)),
        "budget_critical": float(get_preference(db, "budget_critical_threshold", _BUDGET_CRITICAL_DEFAULT)),
    }


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


def _low_budget(db: Session, t: dict[str, float] | None = None) -> list[Notification]:
    if t is None:
        t = _thresholds(db)
    spending = get_spending(db)
    remaining = spending.get("remaining")
    if remaining is None or remaining >= t["budget_warning"]:
        return []
    severity = NotificationSeverity.CRITICAL if remaining < t["budget_critical"] else NotificationSeverity.WARNING
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


def _interviews_without_outcome(db: Session, t: dict[str, float] | None = None) -> list[Notification]:
    if t is None:
        t = _thresholds(db)
    cutoff = datetime.now(UTC) - timedelta(days=int(t["interview_no_outcome_days"]))
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


def _todo_pending(db: Session) -> list[Notification]:
    from ..agenda.models import TodoItem

    count = db.query(func.count(TodoItem.id)).filter(TodoItem.done == False).scalar() or 0  # noqa: E712
    if count == 0:
        return []
    return [
        Notification(
            id=f"todo:pending:{count}",
            type=NotificationType.TODO_PENDING,
            severity=NotificationSeverity.INFO,
            title=f"{count} task da completare",
            body="Hai task aperti nella tua agenda.",
            action_url="/agenda",
            action_label="Apri Agenda",
            dismissible=True,
            sticky=False,
            created_at=datetime.now(UTC),
        )
    ]


_BACKUP_MAX_AGE_DAYS = 7


def _backup_stale(db: Session) -> list[Notification]:
    """Warn if no backup exists or last backup is older than 7 days."""
    import os

    from ..config import settings as app_cfg

    # Skip in dev/test — only fire in production (Render sets RENDER=true)
    if not os.environ.get("RENDER"):
        return []

    # Skip if R2 is not configured
    if not app_cfg.r2_endpoint_url or not app_cfg.r2_access_key_id:
        return []

    try:
        from ..integrations.backup import list_backups

        backups = list_backups()
    except Exception:
        return []

    if not backups:
        return [
            Notification(
                id="backup:missing",
                type=NotificationType.BACKUP_STALE,
                severity=NotificationSeverity.WARNING,
                title="Nessun backup presente",
                body="Crea un backup del database da Impostazioni per proteggere i dati.",
                action_url="/settings",
                action_label="Vai a Impostazioni",
                dismissible=True,
                sticky=True,
                created_at=datetime.now(UTC),
            )
        ]

    latest_str = backups[0].get("last_modified", "")
    if not latest_str:
        return []

    latest = datetime.fromisoformat(latest_str.replace("Z", "+00:00"))
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=UTC)
    age = datetime.now(UTC) - latest
    if age.days < _BACKUP_MAX_AGE_DAYS:
        return []

    return [
        Notification(
            id=f"backup:stale:{age.days}",
            type=NotificationType.BACKUP_STALE,
            severity=NotificationSeverity.WARNING,
            title=f"Backup vecchio ({age.days} giorni)",
            body="L'ultimo backup ha piu' di 7 giorni. Creane uno nuovo da Impostazioni.",
            action_url="/settings",
            action_label="Crea backup",
            dismissible=True,
            sticky=True,
            created_at=datetime.now(UTC),
        )
    ]


def _recent_errors(db: Session) -> list[Notification]:
    """Surface recent 5xx errors from the metrics table."""
    try:
        from ..metrics.models import RequestMetric

        cutoff = datetime.now(UTC) - timedelta(hours=24)
        error_count = (
            db.query(func.count(RequestMetric.id))
            .filter(RequestMetric.created_at >= cutoff, RequestMetric.status_code >= 500)
            .scalar()
            or 0
        )
        if error_count == 0:
            return []

        return [
            Notification(
                id=f"errors:5xx:{error_count}",
                type=NotificationType.APP_ERROR,
                severity=NotificationSeverity.CRITICAL if error_count >= 5 else NotificationSeverity.WARNING,
                title=f"{error_count} errori server (5xx) nelle ultime 24h",
                body="Controlla la pagina Admin per i dettagli sugli endpoint coinvolti.",
                action_url="/admin",
                action_label="Apri Admin",
                dismissible=True,
                sticky=True,
                created_at=datetime.now(UTC),
            )
        ]
    except Exception:
        return []


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
    t = _thresholds(db)

    out: list[Notification] = []
    out.extend(_upcoming_interviews(db))
    out.extend(_low_budget(db, t))
    out.extend(_interviews_without_outcome(db, t))
    out.extend(_db_size_high(db))
    out.extend(_followup_due(db))
    out.extend(_backlog_to_review(db))
    out.extend(_todo_pending(db))
    out.extend(_backup_stale(db))
    out.extend(_recent_errors(db))

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
