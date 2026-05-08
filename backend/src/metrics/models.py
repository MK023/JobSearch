"""Request metrics model for internal telemetry."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database.base import Base


class RequestMetric(Base):
    """Single HTTP request metric — lightweight telemetry row."""

    __tablename__ = "request_metrics"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    endpoint: Mapped[str] = mapped_column(String(200), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    status_code: Mapped[int] = mapped_column(nullable=False)
    duration_ms: Mapped[float] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        Index("idx_metrics_created", "created_at"),
        Index("idx_metrics_endpoint", "endpoint"),
    )
