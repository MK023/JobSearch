"""Job analysis models and enums."""

import enum
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database.base import Base

if TYPE_CHECKING:
    from ..contacts.models import Contact
    from ..cover_letter.models import CoverLetter
    from ..cv.models import CVProfile
    from ..interview.models import Interview

# SQLAlchemy cascade directive shared by child relationships: delete orphans
# when the parent is removed so we don't leak rows tied to a gone analysis.
_CASCADE_ALL_DELETE_ORPHAN = "all, delete-orphan"


class AnalysisStatus(enum.StrEnum):
    """Application tracking status (overall funnel state).

    Per-round granularity (conoscitivo/tecnico/finale, passed/rejected) is
    captured on the Interview model. This enum stays coarse-grained so the
    main UX (history tabs, dashboard counts) stays simple. ``OFFER`` is set
    when the candidate receives a written offer.
    """

    PENDING = "da_valutare"
    APPLIED = "candidato"
    INTERVIEW = "colloquio"
    OFFER = "offerta"
    REJECTED = "scartato"
    REJECTED_BY_COMPANY = "rifiutato"


class AnalysisSource(enum.StrEnum):
    """Origin of a JobAnalysis — drives per-source notification aggregation.

    Each value corresponds to a distinct ingestion path. The notification
    center emits one aggregated card per source so the user can tell at
    a glance which inbox needs attention (e.g. "3 analisi da valutare
    (estensione)" vs "1 analisi da valutare (Cowork)").
    """

    COWORK = "cowork"  # paste flow from /analyze form in the browser UI
    EXTENSION = "extension"  # Chrome extension -> /api/v1/inbox -> analysis
    API = "api"  # direct JSON POST to /api/v1/analyze (programmatic)
    MCP = "mcp"  # MCP server pre-computed import via /api/v1/analysis/import
    MANUAL = "manual"  # fallback (legacy rows before this column existed)
    WORLDWILD = "worldwild"  # promoted from /worldwild discovery (Adzuna et al.)


class JobAnalysis(Base):
    """Persisted job-vs-CV analysis with AI scores, gaps, and cost tracking."""

    __tablename__ = "job_analyses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cv_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cv_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_description: Mapped[str] = mapped_column(Text, nullable=False)
    job_url: Mapped[str | None] = mapped_column(String(500), default="")
    content_hash: Mapped[str | None] = mapped_column(String(64), default="", index=True)

    # Job metadata extracted by AI
    job_summary: Mapped[str | None] = mapped_column(Text, default="")
    company: Mapped[str | None] = mapped_column(String(255), default="")
    role: Mapped[str | None] = mapped_column(String(255), default="")
    location: Mapped[str | None] = mapped_column(String(255), default="")
    work_mode: Mapped[str | None] = mapped_column(String(50), default="")
    salary_info: Mapped[str | None] = mapped_column(String(255), default="")
    # Compact CEFR string (A1/A2/B1/B2/C1/C2/Native) extracted by AI dal JD;
    # ``""`` quando l'annuncio non menziona inglese. Confrontabile come ordinal
    # in Python: rule pre-defined in ``analysis.cefr.compare`` (PR successiva).
    english_level_required: Mapped[str | None] = mapped_column(String(8), nullable=True, default="")

    # Analysis results
    score: Mapped[int | None] = mapped_column(default=0)
    recommendation: Mapped[str | None] = mapped_column(String(20), default="")
    status: Mapped[str | None] = mapped_column(String(20), default=AnalysisStatus.PENDING.value)
    # Origin of the analysis (extension / cowork / manual / mcp / api).
    # Indexed: notification aggregator groups pending by source.
    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=AnalysisSource.MANUAL.value,
        server_default=AnalysisSource.MANUAL.value,
        index=True,
    )
    strengths: Mapped[list[Any] | None] = mapped_column(JSON, default=list)
    gaps: Mapped[list[Any] | None] = mapped_column(JSON, default=list)
    interview_scripts: Mapped[list[Any] | None] = mapped_column(JSON, default=list)
    advice: Mapped[str | None] = mapped_column(Text, default="")
    company_reputation: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=dict)
    salary_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    company_news: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    career_track: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    track_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    benefits: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    recruiter_info: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    experience_required: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    full_response: Mapped[str | None] = mapped_column(Text, default="")

    # Cost tracking
    model_used: Mapped[str | None] = mapped_column(String(50), default="")
    tokens_input: Mapped[int | None] = mapped_column(default=0)
    tokens_output: Mapped[int | None] = mapped_column(default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float, default=0.0)

    # Timestamps
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    followed_up: Mapped[bool | None] = mapped_column(Boolean, default=False)

    # Relationships
    cv: Mapped["CVProfile"] = relationship(back_populates="analyses")
    cover_letters: Mapped[list["CoverLetter"]] = relationship(
        back_populates="analysis",
        cascade=_CASCADE_ALL_DELETE_ORPHAN,
    )
    contacts: Mapped[list["Contact"]] = relationship(
        back_populates="analysis",
        cascade=_CASCADE_ALL_DELETE_ORPHAN,
    )
    interviews: Mapped[list["Interview"]] = relationship(
        back_populates="analysis",
        cascade=_CASCADE_ALL_DELETE_ORPHAN,
        order_by="Interview.round_number",
    )

    @property
    def interview(self) -> "Interview | None":
        """Back-compat alias: latest round (highest round_number).

        Code written before the multi-round migration accesses
        ``analysis.interview`` as a single object. We keep the attribute
        but resolve it to the most recent round so existing call sites
        (templates, services) keep working unchanged.
        """
        rounds = self.interviews or []
        return rounds[-1] if rounds else None

    __table_args__ = (
        Index("idx_analyses_score", "score"),
        Index("idx_analyses_status", "status"),
        Index("idx_analyses_created", "created_at"),
        Index("idx_analyses_cv_id", "cv_id"),
    )


class AppSettings(Base):
    """Singleton row for app-wide settings and running totals."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    anthropic_budget: Mapped[float | None] = mapped_column(Float, default=0.0)

    # Running totals (updated on each insert/delete)
    total_cost_usd: Mapped[float | None] = mapped_column(Float, default=0.0)
    total_tokens_input: Mapped[int | None] = mapped_column(default=0)
    total_tokens_output: Mapped[int | None] = mapped_column(default=0)
    total_analyses: Mapped[int | None] = mapped_column(default=0)
    total_cover_letters: Mapped[int | None] = mapped_column(default=0)

    # Daily counters (auto-reset on date change)
    today_date: Mapped[str | None] = mapped_column(String(10), default="")
    today_cost_usd: Mapped[float | None] = mapped_column(Float, default=0.0)
    today_tokens_input: Mapped[int | None] = mapped_column(default=0)
    today_tokens_output: Mapped[int | None] = mapped_column(default=0)
    today_analyses: Mapped[int | None] = mapped_column(default=0)

    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
