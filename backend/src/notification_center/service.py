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

import logging
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..analysis.models import AnalysisStatus, JobAnalysis
from ..dashboard.service import get_followup_alerts, get_spending
from ..inbox.models import InboxItem, InboxStatus
from ..interview.models import Interview
from ..interview.service import get_upcoming_interviews
from ..preferences.service import get_preference
from .models import Notification, NotificationDismissal, NotificationSeverity, NotificationType

logger = logging.getLogger(__name__)

# Default thresholds — overridable via Settings > Parametri operativi.
_INTERVIEW_UPCOMING_HOURS = 24
_INTERVIEW_NO_OUTCOME_DAYS_DEFAULT = 3
_BUDGET_WARNING_DEFAULT = 1.00
_BUDGET_CRITICAL_DEFAULT = 0.50
_DB_SIZE_WARNING_MB = 800  # 80% of 1GB Neon free tier
_BACKLOG_THRESHOLD = 1

# Per-type drill-down URLs: each aggregated card sends the user to the page
# that renders the underlying items individually, not back to /notifications
# (which would re-show the same aggregated card — circular link UX bug).
_FOLLOWUP_LIST_URL = "/agenda"  # get_followup_alerts rendered per-item on the agenda
_INTERVIEW_LIST_URL = "/interviews"  # past rounds without outcome visible there


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
    if not rows:
        return []

    if len(rows) == 1:
        interview, analysis = rows[0]
        scheduled: datetime = interview.scheduled_at
        return [
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
        ]

    # Aggregate: multiple interview rounds missing outcome
    count = len(rows)
    companies = [str(analysis.company) for _, analysis in rows[:3] if analysis.company]
    others = count - len(companies)
    company_line = ", ".join(companies) if companies else ""
    if others > 0 and company_line:
        company_line += f" e altri {others}"
    body = (company_line + ". " if company_line else "") + "Logga gli esiti per mantenere il funnel pulito."
    return [
        Notification(
            id=f"interview_outcome:aggregated:{count}",
            type=NotificationType.INTERVIEW_NO_OUTCOME,
            severity=NotificationSeverity.WARNING,
            title=f"{count} colloqui senza esito registrato",
            body=body,
            action_url=_INTERVIEW_LIST_URL,
            action_label="Apri colloqui",
            dismissible=True,
            sticky=True,
            created_at=datetime.now(UTC),
        )
    ]


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
    if not alerts:
        return []
    now = datetime.now(UTC)

    if len(alerts) == 1:
        a = alerts[0]
        applied: datetime | None = a.applied_at  # type: ignore[assignment]
        return [
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
        ]

    # Aggregate: multiple follow-ups pending
    count = len(alerts)
    companies = [str(a.company) for a in alerts[:3] if a.company]
    others = count - len(companies)
    company_line = ", ".join(companies) if companies else ""
    if others > 0 and company_line:
        company_line += f" e altri {others}"
    body = (company_line + ". " if company_line else "") + "Valuta un remind ai recruiter."
    return [
        Notification(
            id=f"followup:aggregated:{count}",
            type=NotificationType.FOLLOWUP_DUE,
            severity=NotificationSeverity.INFO,
            title=f"{count} follow-up suggeriti",
            body=body,
            action_url=_FOLLOWUP_LIST_URL,
            action_label="Apri agenda",
            dismissible=True,
            sticky=False,
            created_at=now,
        )
    ]


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
        logger.exception("notification_center: backup listing failed")
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
        logger.exception("notification_center: recent_errors rule failed")
        return []


def _news_available(db: Session) -> list[Notification]:
    """Notify when there are recent news for companies in active candidatures."""
    try:
        from ..integrations.news import NewsCache

        active_statuses = [AnalysisStatus.APPLIED.value, AnalysisStatus.INTERVIEW.value]
        companies = [
            r[0]
            for r in db.query(JobAnalysis.company)
            .filter(JobAnalysis.status.in_(active_statuses), JobAnalysis.company.isnot(None), JobAnalysis.company != "")
            .distinct()
            .all()
        ]
        if not companies:
            return []

        cutoff = datetime.now(UTC) - timedelta(days=7)
        news_count = (
            db.query(func.count(NewsCache.id))
            .filter(NewsCache.company_name.in_([c.lower() for c in companies]), NewsCache.fetched_at >= cutoff)
            .scalar()
            or 0
        )
        if news_count == 0:
            return []

        return [
            Notification(
                id=f"news:available:{news_count}",
                type=NotificationType.NEWS_AVAILABLE,
                severity=NotificationSeverity.INFO,
                title=f"News disponibili per {news_count} aziend{'a' if news_count == 1 else 'e'}",
                body="Controlla la pagina News per le ultime notizie sulle aziende delle candidature attive.",
                action_url="/news",
                action_label="Vedi news",
                dismissible=True,
                sticky=False,
                created_at=datetime.now(UTC),
            )
        ]
    except Exception:
        logger.exception("notification_center: news_available rule failed")
        return []


def _analytics_available(db: Session) -> list[Notification]:
    """Notify when the user has enough triaged post-v7 analyses to unlock /analytics."""
    try:
        from ..analytics_page.service import UNLOCK_THRESHOLD, get_lock_state

        lock = get_lock_state(db)
        if lock.get("locked", True):
            return []

        new_since = lock.get("new_since_last", 0) or 0
        has_run_history = lock.get("last_run_at") is not None
        nid = f"analytics:available:{new_since}"
        title = (
            f"Analisi disponibile: {new_since} nuove valutazioni dall'ultima esecuzione"
            if has_run_history
            else f"Prima analisi disponibile: {new_since} candidature pronte"
        )
        body = (
            "Soglia di "
            + str(UNLOCK_THRESHOLD)
            + " raggiunta. Apri la pagina Analytics per eseguire una nuova analisi e aggiornare il profilo."
        )
        return [
            Notification(
                id=nid,
                type=NotificationType.ANALYTICS_AVAILABLE,
                severity=NotificationSeverity.INFO,
                title=title,
                body=body,
                action_url="/analytics",
                action_label="Apri Analytics",
                dismissible=True,
                sticky=False,
                created_at=datetime.now(UTC),
            )
        ]
    except Exception:
        logger.exception("notification_center: analytics_available rule failed")
        return []


def _inbox_ready(db: Session) -> list[Notification]:
    """Aggregate: inbox-originated analyses landed in history, still awaiting triage."""
    try:
        cutoff = datetime.now(UTC) - timedelta(days=7)
        count = (
            db.query(func.count(InboxItem.id))
            .join(JobAnalysis, InboxItem.analysis_id == JobAnalysis.id)
            .filter(
                InboxItem.status == InboxStatus.DONE.value,
                InboxItem.processed_at >= cutoff,
                JobAnalysis.status == AnalysisStatus.PENDING.value,
            )
            .scalar()
            or 0
        )
        if count == 0:
            return []
        title = "1 nuova analisi dal Chrome extension" if count == 1 else f"{count} nuove analisi dal Chrome extension"
        return [
            Notification(
                id=f"inbox:ready:{count}",
                type=NotificationType.INBOX_ANALYSIS_READY,
                severity=NotificationSeverity.INFO,
                title=title,
                body="Arrivate tramite paste del browser, pronte da valutare.",
                action_url="/history#valutazione",
                action_label="Apri valutazione",
                dismissible=True,
                sticky=False,
                created_at=datetime.now(UTC),
            )
        ]
    except Exception:
        logger.exception("notification_center: inbox_ready rule failed")
        return []


def _inbox_errors(db: Session) -> list[Notification]:
    """Inbox items that failed analysis. Sticky — require attention. Aggregated when >=2."""
    try:
        cutoff = datetime.now(UTC) - timedelta(days=7)
        errored = (
            db.query(InboxItem)
            .filter(
                InboxItem.status == InboxStatus.ERROR.value,
                InboxItem.processed_at >= cutoff,
            )
            .order_by(InboxItem.processed_at.desc())
            .limit(20)
            .all()
        )
        if not errored:
            return []

        if len(errored) == 1:
            item = errored[0]
            err_msg = str(item.error_message or "Errore sconosciuto")[:200]
            source = str(item.source or "inbox")
            processed = cast("datetime | None", item.processed_at)
            # No action_url: inbox errors have no dedicated drill-down page yet.
            # User acknowledges via the explicit × dismiss button.
            return [
                Notification(
                    id=f"inbox:error:{item.id}",
                    type=NotificationType.INBOX_ERROR,
                    severity=NotificationSeverity.WARNING,
                    title=f"Errore analisi inbox ({source})",
                    body=err_msg,
                    action_url=None,
                    action_label=None,
                    dismissible=True,
                    sticky=True,
                    created_at=processed or datetime.now(UTC),
                )
            ]

        # Aggregate multiple errors
        count = len(errored)
        first_msgs = [str(item.error_message or "errore")[:60] for item in errored[:2]]
        preview = " | ".join(first_msgs)
        if count > 2:
            preview += f" (+ altri {count - 2})"
        first_processed = cast("datetime | None", errored[0].processed_at)
        return [
            Notification(
                id=f"inbox:error:aggregated:{count}",
                type=NotificationType.INBOX_ERROR,
                severity=NotificationSeverity.WARNING,
                title=f"{count} errori analisi inbox",
                body=preview[:400],
                action_url=None,
                action_label=None,
                dismissible=True,
                sticky=True,
                created_at=first_processed or datetime.now(UTC),
            )
        ]
    except Exception:
        logger.exception("notification_center: inbox_errors rule failed")
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
    out.extend(_news_available(db))
    out.extend(_analytics_available(db))
    out.extend(_inbox_ready(db))
    out.extend(_inbox_errors(db))

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
