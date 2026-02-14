import logging
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String, Text, create_engine, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import QueuePool

from .config import settings

logger = logging.getLogger(__name__)

engine = create_engine(
    settings.effective_database_url,
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
    applied_at = Column(DateTime, nullable=True)
    followed_up = Column(Boolean, default=False)

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
    # Running totals (aggiornati ad ogni insert/delete, queryabili direttamente)
    total_cost_usd = Column(Float, default=0.0)
    total_tokens_input = Column(Integer, default=0)
    total_tokens_output = Column(Integer, default=0)
    total_analyses = Column(Integer, default=0)
    total_cover_letters = Column(Integer, default=0)
    # Contatori giornalieri (reset automatico al cambio data)
    today_date = Column(String(10), default="")
    today_cost_usd = Column(Float, default=0.0)
    today_tokens_input = Column(Integer, default=0)
    today_tokens_output = Column(Integer, default=0)
    today_analyses = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id = Column(UUID(as_uuid=True), nullable=True)
    name = Column(String(255), default="")
    email = Column(String(255), default="")
    phone = Column(String(50), default="")
    company = Column(String(255), default="")
    linkedin_url = Column(String(500), default="")
    notes = Column(Text, default="")
    source = Column(String(20), default="manual")  # manual / vcard
    created_at = Column(DateTime, default=datetime.utcnow)


class GlassdoorCache(Base):
    __tablename__ = "glassdoor_cache"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_name = Column(String(255), unique=True, index=True, nullable=False)
    glassdoor_data = Column(Text, default="")
    rating = Column(Float, nullable=True)
    review_count = Column(Integer, nullable=True)
    fetched_at = Column(DateTime, default=datetime.utcnow)


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
        _add_column_if_missing(conn, "job_analyses", "applied_at", "TIMESTAMP")
        _add_column_if_missing(conn, "job_analyses", "followed_up", "BOOLEAN DEFAULT FALSE")
        for col, ctype in [
            ("total_cost_usd", "FLOAT DEFAULT 0.0"),
            ("total_tokens_input", "INTEGER DEFAULT 0"),
            ("total_tokens_output", "INTEGER DEFAULT 0"),
            ("total_analyses", "INTEGER DEFAULT 0"),
            ("total_cover_letters", "INTEGER DEFAULT 0"),
            ("today_date", "VARCHAR(10) DEFAULT ''"),
            ("today_cost_usd", "FLOAT DEFAULT 0.0"),
            ("today_tokens_input", "INTEGER DEFAULT 0"),
            ("today_tokens_output", "INTEGER DEFAULT 0"),
            ("today_analyses", "INTEGER DEFAULT 0"),
        ]:
            _add_column_if_missing(conn, "app_settings", col, ctype)
    _seed_spending_totals()
    _seed_applied_at()


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


def _seed_spending_totals():
    """Calcola i totali iniziali dai dati esistenti se app_settings e' vuota."""
    from datetime import date, time

    db = SessionLocal()
    try:
        s = db.query(AppSettings).first()
        if not s:
            s = AppSettings(id=1)
            db.add(s)
            db.commit()
            db.refresh(s)

        existing = db.query(func.count(JobAnalysis.id)).scalar() or 0
        if (s.total_analyses or 0) == 0 and existing > 0:
            a = db.query(
                func.coalesce(func.sum(JobAnalysis.cost_usd), 0.0),
                func.coalesce(func.sum(JobAnalysis.tokens_input), 0),
                func.coalesce(func.sum(JobAnalysis.tokens_output), 0),
                func.count(JobAnalysis.id),
            ).first()
            cl = db.query(
                func.coalesce(func.sum(CoverLetter.cost_usd), 0.0),
                func.coalesce(func.sum(CoverLetter.tokens_input), 0),
                func.coalesce(func.sum(CoverLetter.tokens_output), 0),
                func.count(CoverLetter.id),
            ).first()
            s.total_cost_usd = round(float(a[0]) + float(cl[0]), 6)
            s.total_tokens_input = int(a[1]) + int(cl[1])
            s.total_tokens_output = int(a[2]) + int(cl[2])
            s.total_analyses = int(a[3])
            s.total_cover_letters = int(cl[3])

            today_start = datetime.combine(date.today(), time.min)
            at = db.query(
                func.coalesce(func.sum(JobAnalysis.cost_usd), 0.0),
                func.coalesce(func.sum(JobAnalysis.tokens_input), 0),
                func.coalesce(func.sum(JobAnalysis.tokens_output), 0),
                func.count(JobAnalysis.id),
            ).filter(JobAnalysis.created_at >= today_start).first()
            ct = db.query(
                func.coalesce(func.sum(CoverLetter.cost_usd), 0.0),
                func.coalesce(func.sum(CoverLetter.tokens_input), 0),
                func.coalesce(func.sum(CoverLetter.tokens_output), 0),
            ).filter(CoverLetter.created_at >= today_start).first()
            s.today_date = date.today().isoformat()
            s.today_cost_usd = round(float(at[0]) + float(ct[0]), 6)
            s.today_tokens_input = int(at[1]) + int(ct[1])
            s.today_tokens_output = int(at[2]) + int(ct[2])
            s.today_analyses = int(at[3])
            db.commit()
            logger.info("Totali inizializzati: %d analisi, %d cover letters, $%.4f", s.total_analyses, s.total_cover_letters, s.total_cost_usd)
    finally:
        db.close()


def _seed_applied_at():
    """Imposta applied_at per analisi gia' in stato candidato/colloquio che non ce l'hanno."""
    db = SessionLocal()
    try:
        updated = (
            db.query(JobAnalysis)
            .filter(
                JobAnalysis.status.in_(["candidato", "colloquio"]),
                JobAnalysis.applied_at.is_(None),
            )
            .update({JobAnalysis.applied_at: JobAnalysis.created_at}, synchronize_session="fetch")
        )
        if updated:
            db.commit()
            logger.info("Seed applied_at: %d analisi aggiornate", updated)
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
