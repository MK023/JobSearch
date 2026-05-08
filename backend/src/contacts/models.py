"""Recruiter contact model."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database.base import Base

if TYPE_CHECKING:
    from ..analysis.models import JobAnalysis


class Contact(Base):
    """Recruiter or hiring manager contact, optionally linked to an analysis."""

    __tablename__ = "contacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("job_analyses.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str | None] = mapped_column(String(255), default="")
    email: Mapped[str | None] = mapped_column(String(255), default="")
    phone: Mapped[str | None] = mapped_column(String(50), default="")
    company: Mapped[str | None] = mapped_column(String(255), default="")
    linkedin_url: Mapped[str | None] = mapped_column(String(500), default="")
    notes: Mapped[str | None] = mapped_column(Text, default="")
    source: Mapped[str | None] = mapped_column(String(20), default="manual")
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )

    analysis: Mapped["JobAnalysis | None"] = relationship(back_populates="contacts")
