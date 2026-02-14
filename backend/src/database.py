import logging
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Index, Integer, String, Text, create_engine, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import QueuePool

from .config import settings

logger = logging.getLogger(__name__)

engine = create_engine(
    settings.database_url,
    poolclass=QueuePool,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class CVProfile(Base):
    __tablename__ = "cv_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    raw_text = Column(Text, nullable=False)
    name = Column(String(255), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class JobAnalysis(Base):
    __tablename__ = "job_analyses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cv_id = Column(UUID(as_uuid=True), nullable=False)
    job_description = Column(Text, nullable=False)
    job_url = Column(String(500), default="")
    content_hash = Column(String(64), default="", index=True)
    job_summary = Column(Text, default="")
    company = Column(String(255), default="")
    role = Column(String(255), default="")
    location = Column(String(255), default="")
    work_mode = Column(String(50), default="")  # remoto / ibrido / in sede
    salary_info = Column(String(255), default="")
    score = Column(Integer, default=0)
    recommendation = Column(String(20), default="")
    status = Column(String(20), default="da_valutare")
    strengths = Column(Text, default="")
    gaps = Column(Text, default="")
    interview_scripts = Column(Text, default="")
    advice = Column(Text, default="")
    company_reputation = Column(Text, default="")  # JSON: glassdoor_estimate, pros, cons
    full_response = Column(Text, default="")
    model_used = Column(String(50), default="")
    tokens_input = Column(Integer, default=0)
    tokens_output = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_analyses_score", "score"),
        Index("idx_analyses_status", "status"),
        Index("idx_analyses_created", "created_at"),
        Index("idx_analyses_recommendation", "recommendation"),
    )


class AppSettings(Base):
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, default=1)
    anthropic_budget = Column(Float, default=0.0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CoverLetter(Base):
    __tablename__ = "cover_letters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id = Column(UUID(as_uuid=True), nullable=False)
    language = Column(String(20), default="italiano")
    content = Column(Text, default="")
    subject_lines = Column(Text, default="")  # JSON list
    model_used = Column(String(50), default="")
    tokens_input = Column(Integer, default=0)
    tokens_output = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    logger.info("Creazione/verifica tabelle database")
    Base.metadata.create_all(bind=engine)
    logger.info("Tabelle verificate: %s", ", ".join(Base.metadata.tables.keys()))
    # Auto-migrate: add columns that create_all won't add to existing tables
    with engine.connect() as conn:
        _add_column_if_missing(conn, "job_analyses", "company_reputation", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "job_analyses", "content_hash", "VARCHAR(64) DEFAULT ''")


def _add_column_if_missing(conn, table: str, column: str, col_type: str):
    result = conn.execute(
        text("SELECT column_name FROM information_schema.columns WHERE table_name=:t AND column_name=:c"),
        {"t": table, "c": column},
    )
    if result.fetchone() is None:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
        conn.commit()
        logger.info("Migrazione: aggiunta colonna %s.%s (%s)", table, column, col_type)
    else:
        logger.debug("Colonna %s.%s già presente, skip migrazione", table, column)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
