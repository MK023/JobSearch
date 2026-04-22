"""ORM model for the LinkedIn Job Applications import.

Shape mirrors the CSV columns from LinkedIn's ``Get a copy of your data``
export (file ``Job Applications.csv`` inside the archive).
"""

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Index, Integer, Text, UniqueConstraint

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

    id = Column(Integer, primary_key=True, autoincrement=True)
    application_date = Column(DateTime(timezone=True), nullable=True, index=True)
    contact_email = Column(Text, nullable=True)
    contact_phone = Column(Text, nullable=True)
    company_name = Column(Text, nullable=True)
    job_title = Column(Text, nullable=True)
    job_url = Column(Text, nullable=True)
    resume_name = Column(Text, nullable=True)
    question_and_answers = Column(Text, nullable=True)
    import_source = Column(Text, nullable=False, default="linkedin_easy_apply")
    imported_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
