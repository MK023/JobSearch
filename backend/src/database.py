import uuid
from datetime import datetime

from sqlalchemy import create_engine, Column, String, Text, DateTime, Integer, Float, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import QueuePool

from .config import settings

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


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
