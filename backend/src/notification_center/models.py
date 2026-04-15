"""Notification data model.

Notifications are COMPUTED, not persisted — they are a projection of the
current state of the app (interviews, budget, DB size, etc.). No table,
no migrations. This keeps them always in sync with reality and avoids a
parallel state machine.

Client-side dismiss is only meaningful for ``dismissible=True`` entries:
the UI writes dismissed ids into ``sessionStorage`` and hides them for
the current tab session. Sticky entries (critical states) ignore the
dismiss list.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


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


class Notification(BaseModel):
    """A single actionable alert surfaced to the user."""

    id: str = Field(..., description="Stable id derived from the source (e.g. interview:<uuid>).")
    type: NotificationType
    severity: NotificationSeverity
    title: str = Field(..., max_length=200)
    body: str = Field(..., max_length=500)
    action_url: str | None = Field(None, description="Where the primary action navigates.")
    action_label: str | None = Field(None, max_length=60)
    dismissible: bool = Field(False, description="User can hide for the session via sessionStorage.")
    sticky: bool = Field(True, description="Re-surfaces until the underlying state changes.")
    created_at: datetime
