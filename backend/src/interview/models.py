"""Interview scheduling model — multi-round capable."""

import enum
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database.base import Base

# Ensure InterviewFile is importable (relationship target)
from .file_models import InterviewFile  # noqa: F401

if TYPE_CHECKING:
    from ..analysis.models import JobAnalysis


class InterviewOutcome(enum.StrEnum):
    """Result of a single interview round.

    NULL on the column means "round is still future / outcome not yet
    logged". PENDING is reserved for an explicit "waiting for client
    feedback" state set by the user.
    """

    PASSED = "passed"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    PENDING = "pending"


class Interview(Base):
    """One round of an interview process linked to a job analysis.

    A JobAnalysis can have multiple rounds (conoscitivo → tecnico → finale →
    offer round), ordered by ``round_number``. Each round carries its own
    outcome; the parent JobAnalysis.status reflects the global funnel state.
    """

    __tablename__ = "interviews"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("job_analyses.id", ondelete="CASCADE"),
        nullable=False,
    )
    round_number: Mapped[int] = mapped_column(nullable=False, default=1)

    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # platform values: google_meet / teams / zoom / phone / in_person / other
    platform: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # interview_type values: tecnico / hr / conoscitivo / finale / other
    interview_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # outcome values: passed / rejected / withdrawn / pending. NULL means not yet logged.
    outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)
    interviewer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recruiter_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recruiter_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meeting_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    meeting_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    access_pin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    analysis: Mapped["JobAnalysis"] = relationship(
        back_populates="interviews",
        foreign_keys=[analysis_id],
    )
    files: Mapped[list["InterviewFile"]] = relationship(
        back_populates="interview",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_interviews_scheduled", "scheduled_at"),
        Index("idx_interviews_analysis_id", "analysis_id"),
    )
