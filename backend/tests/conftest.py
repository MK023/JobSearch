"""Shared test fixtures."""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analysis.models import AnalysisStatus, AppSettings, JobAnalysis
from src.audit.models import AuditLog
from src.auth.models import User
from src.contacts.models import Contact
from src.cover_letter.models import CoverLetter
from src.cv.models import CVProfile
from src.database.base import Base
from src.integrations.cache import NullCacheService
from src.integrations.glassdoor import GlassdoorCache
from src.interview.models import Interview
from src.notifications.models import NotificationLog

# Models must be imported so Base.metadata.create_all() sees all tables.
_ALL_MODELS = [AppSettings, CoverLetter, Contact, GlassdoorCache, AuditLog, NotificationLog, Interview]


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing.

    Note: SQLite doesn't support all PostgreSQL features (JSONB, UUID),
    but works for basic service logic testing.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def test_user(db_session):
    """Create a test user."""
    user = User(
        id=uuid.uuid4(),
        email="test@example.com",
        password_hash="$2b$12$fakehash",
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def test_cv(db_session, test_user):
    """Create a test CV profile."""
    cv = CVProfile(
        id=uuid.uuid4(),
        user_id=test_user.id,
        raw_text="Test CV content with enough text to pass validation checks for the service layer.",
        name="Test User",
    )
    db_session.add(cv)
    db_session.commit()
    return cv


@pytest.fixture
def test_analysis(db_session, test_cv):
    """Create a test job analysis."""
    analysis = JobAnalysis(
        id=uuid.uuid4(),
        cv_id=test_cv.id,
        job_description="Test job description for a software engineer position at a tech company.",
        company="TestCorp",
        role="Software Engineer",
        score=75,
        recommendation="CONSIDER",
        status=AnalysisStatus.PENDING,
        strengths=["Python", "FastAPI", "SQL"],
        gaps=[{"gap": "Kubernetes", "severity": "importante", "closable": True, "how": "Online course"}],
        interview_scripts=[{"question": "Tell me about yourself", "suggested_answer": "I am a developer..."}],
        advice="Good match overall.",
        model_used="claude-haiku-4-5-20251001",
        tokens_input=1000,
        tokens_output=500,
        cost_usd=0.005,
        content_hash="abc123",
    )
    db_session.add(analysis)
    db_session.commit()
    return analysis


@pytest.fixture
def null_cache():
    """No-op cache for testing."""
    return NullCacheService()
