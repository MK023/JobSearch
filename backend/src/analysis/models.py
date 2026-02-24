"""Job analysis models and enums."""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..database.base import Base


class AnalysisStatus(enum.StrEnum):
    """Application tracking status."""

    PENDING = "da_valutare"
    APPLIED = "candidato"
    INTERVIEW = "colloquio"
    REJECTED = "scartato"


class JobAnalysis(Base):
    __tablename__ = "job_analyses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cv_id = Column(
        UUID(as_uuid=True),
        ForeignKey("cv_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_description = Column(Text, nullable=False)
    job_url = Column(String(500), default="")
    content_hash = Column(String(64), default="", index=True)

    # Job metadata extracted by AI
    job_summary = Column(Text, default="")
    company = Column(String(255), default="")
    role = Column(String(255), default="")
    location = Column(String(255), default="")
    work_mode = Column(String(50), default="")
    salary_info = Column(String(255), default="")

    # Analysis results
    score = Column(Integer, default=0)
    recommendation = Column(String(20), default="")
    status = Column(
        SQLEnum(AnalysisStatus, values_callable=lambda e: [s.value for s in e]),
        default=AnalysisStatus.PENDING,
    )
    strengths = Column(JSON, default=list)
    gaps = Column(JSON, default=list)
    interview_scripts = Column(JSON, default=list)
    advice = Column(Text, default="")
    company_reputation = Column(JSON, default=dict)
    full_response = Column(Text, default="")

    # Cost tracking
    model_used = Column(String(50), default="")
    tokens_input = Column(Integer, default=0)
    tokens_output = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    applied_at = Column(DateTime(timezone=True), nullable=True)
    followed_up = Column(Boolean, default=False)

    # Relationships
    cv = relationship("CVProfile", back_populates="analyses")
    cover_letters = relationship("CoverLetter", back_populates="analysis", cascade="all, delete-orphan")
    contacts = relationship("Contact", back_populates="analysis", cascade="all, delete-orphan")
    interview = relationship("Interview", back_populates="analysis", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_analyses_score", "score"),
        Index("idx_analyses_status", "status"),
        Index("idx_analyses_created", "created_at"),
        Index("idx_analyses_cv_id", "cv_id"),
    )


class AppSettings(Base):
    """Singleton row for app-wide settings and running totals."""

    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, default=1)
    anthropic_budget = Column(Float, default=0.0)

    # Running totals (updated on each insert/delete)
    total_cost_usd = Column(Float, default=0.0)
    total_tokens_input = Column(Integer, default=0)
    total_tokens_output = Column(Integer, default=0)
    total_analyses = Column(Integer, default=0)
    total_cover_letters = Column(Integer, default=0)

    # Daily counters (auto-reset on date change)
    today_date = Column(String(10), default="")
    today_cost_usd = Column(Float, default=0.0)
    today_tokens_input = Column(Integer, default=0)
    today_tokens_output = Column(Integer, default=0)
    today_analyses = Column(Integer, default=0)

    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
