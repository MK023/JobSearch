"""ORM model for the LinkedIn Job Applications import.

Shape mirrors the CSV columns from LinkedIn's ``Get a copy of your data``
export (file ``Job Applications.csv`` inside the archive).
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database.base import Base


class LinkedinApplication(Base):
    """One row per LinkedIn Easy Apply submission."""

    __tablename__ = "linkedin_applications"
    __table_args__ = (
        UniqueConstraint("job_url", "application_date", name="uq_linkedin_apps_url_date"),
        Index("ix_linkedin_apps_company", "company_name"),
        Index("ix_linkedin_apps_title", "job_title"),
        Index("ix_linkedin_apps_date", "application_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    application_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    contact_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    resume_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    question_and_answers: Mapped[str | None] = mapped_column(Text, nullable=True)
    import_source: Mapped[str] = mapped_column(Text, nullable=False, default="linkedin_easy_apply")
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
