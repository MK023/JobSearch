"""Cover letter model."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database.base import Base

if TYPE_CHECKING:
    from ..analysis.models import JobAnalysis


class CoverLetter(Base):
    """AI-generated cover letter linked to a job analysis."""

    __tablename__ = "cover_letters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("job_analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    language: Mapped[str | None] = mapped_column(String(20), default="italiano")
    content: Mapped[str | None] = mapped_column(Text, default="")
    subject_lines: Mapped[list[Any] | None] = mapped_column(JSON, default=list)
    model_used: Mapped[str | None] = mapped_column(String(50), default="")
    tokens_input: Mapped[int | None] = mapped_column(default=0)
    tokens_output: Mapped[int | None] = mapped_column(default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )

    analysis: Mapped["JobAnalysis"] = relationship(back_populates="cover_letters")
