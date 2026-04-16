"""Request metrics model for internal telemetry."""

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Float, Index, Integer, String

from ..database.base import Base


class RequestMetric(Base):
    """Single HTTP request metric — lightweight telemetry row."""

    __tablename__ = "request_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    endpoint = Column(String(200), nullable=False)
    method = Column(String(10), nullable=False)
    status_code = Column(Integer, nullable=False)
    duration_ms = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))

    __table_args__ = (
        Index("idx_metrics_created", "created_at"),
        Index("idx_metrics_endpoint", "endpoint"),
    )
