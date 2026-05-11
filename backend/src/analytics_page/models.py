"""Analytics persistence models.

- AnalyticsRun: snapshot of one analytics pass (stats + discriminant + bias)
- UserProfile: current learned preferences used to steer the AI prompt
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database.base import Base


class AnalyticsRun(Base):
    """Snapshot of an analytics run — saved every time /analytics/run is triggered."""

    __tablename__ = "analytics_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )
    analyses_count: Mapped[int] = mapped_column(nullable=False, default=0)
    # ``triggered_by`` keeps SQL nullable for back-compat with rows seeded
    # before the column had a server default. Values used in code:
    # ``"manual"``, ``"auto_threshold"``.
    triggered_by: Mapped[str | None] = mapped_column(String(20), default="manual")
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class UserProfile(Base):
    """Current learned profile — single row per user, updated by each analytics run."""

    __tablename__ = "user_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    source_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analytics_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    profile: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # Cached summary shown in the prompt — keeps token count low
    prompt_snippet: Mapped[str | None] = mapped_column(Text, default="")

    __table_args__ = (Index("idx_user_profiles_source_run_id", "source_run_id"),)
