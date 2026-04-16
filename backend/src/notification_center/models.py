"""Notification data model.

Notifications are COMPUTED, not persisted — they are a projection of the
current state of the app (interviews, budget, DB size, etc.). This keeps
them always in sync with reality and avoids a parallel state machine.

Dismissals ARE persisted in the ``notification_dismissals`` table so that
the sidebar badge accurately reflects what the user has acknowledged.
When the underlying state that generated a notification changes (e.g.
interview outcome logged), the notification simply stops being generated
and the stale dismissal row becomes inert.
"""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Integer, String

from ..database.base import Base


class NotificationSeverity(StrEnum):
    """Visual weight. Drives the badge colour and ordering in the UI."""

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class NotificationType(StrEnum):
    """Semantic category. Used for icons and grouping in the UI."""

    INTERVIEW_UPCOMING = "interview_upcoming"
    INTERVIEW_NO_OUTCOME = "interview_no_outcome"
    BUDGET_LOW = "budget_low"
    DB_SIZE_HIGH = "db_size_high"
    FOLLOWUP_DUE = "followup_due"
    BACKLOG_TO_REVIEW = "backlog_to_review"
    TODO_PENDING = "todo_pending"


class NotificationDismissal(Base):
    """Persisted record that the user dismissed a computed notification."""

    __tablename__ = "notification_dismissals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    notification_id = Column(String(200), nullable=False, unique=True, index=True)
    dismissed_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


class Notification(BaseModel):
    """A single actionable alert surfaced to the user."""

    id: str = Field(..., description="Stable id derived from the source (e.g. interview:<uuid>).")
    type: NotificationType
    severity: NotificationSeverity
    title: str = Field(..., max_length=200)
    body: str = Field(..., max_length=500)
    action_url: str | None = Field(None, description="Where the primary action navigates.")
    action_label: str | None = Field(None, max_length=60)
    dismissible: bool = Field(True, description="User can dismiss; persisted server-side.")
    sticky: bool = Field(True, description="Re-surfaces until the underlying state changes.")
    created_at: datetime
