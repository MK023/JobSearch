"""Analytics persistence models.

- AnalyticsRun: snapshot of one analytics pass (stats + discriminant + bias)
- UserProfile: current learned preferences used to steer the AI prompt
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from ..database.base import Base


class AnalyticsRun(Base):
    """Snapshot of an analytics run — saved every time /analytics/run is triggered."""

    __tablename__ = "analytics_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True)
    analyses_count = Column(Integer, nullable=False, default=0)
    triggered_by = Column(String(20), default="manual")  # "manual", "auto_threshold"
    snapshot = Column(JSON, nullable=False, default=dict)  # full analytics output


class UserProfile(Base):
    """Current learned profile — single row per user, updated by each analytics run."""

    __tablename__ = "user_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    source_run_id = Column(UUID(as_uuid=True), ForeignKey("analytics_runs.id", ondelete="SET NULL"), nullable=True)
    profile = Column(JSON, nullable=False, default=dict)
    # Cached summary shown in the prompt — keeps token count low
    prompt_snippet = Column(Text, default="")
