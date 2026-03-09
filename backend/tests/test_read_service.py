"""Tests for read-only service functions (candidature queries, contacts search)."""

import uuid
from datetime import UTC, datetime, timedelta

from src.analysis.models import AnalysisStatus, JobAnalysis
from src.analysis.service import (
    get_candidature,
    get_candidature_by_date_range,
    get_stale_candidature,
    get_top_candidature,
    search_candidature,
)
from src.contacts.models import Contact
from src.contacts.service import search_all_contacts


def _make_analysis(db_session, test_cv, **overrides):
    """Helper to create a JobAnalysis with defaults."""
    defaults = {
        "id": uuid.uuid4(),
        "cv_id": test_cv.id,
        "job_description": "Test job description.",
        "company": "TestCorp",
        "role": "Software Engineer",
        "score": 75,
        "status": AnalysisStatus.PENDING,
        "content_hash": uuid.uuid4().hex[:16],
    }
    defaults.update(overrides)
    a = JobAnalysis(**defaults)
    db_session.add(a)
    db_session.flush()
    return a


class TestGetCandidature:
    def test_returns_all_without_filter(self, db_session, test_cv):
        _make_analysis(db_session, test_cv, company="Alpha")
        _make_analysis(db_session, test_cv, company="Beta")
        result = get_candidature(db_session)
        assert len(result) == 2

    def test_filters_by_status(self, db_session, test_cv):
        _make_analysis(db_session, test_cv, status=AnalysisStatus.APPLIED)
        _make_analysis(db_session, test_cv, status=AnalysisStatus.PENDING)
        result = get_candidature(db_session, status="candidato")
        assert len(result) == 1
        assert result[0].status == AnalysisStatus.APPLIED

    def test_invalid_status_returns_empty(self, db_session, test_cv):
        _make_analysis(db_session, test_cv)
        result = get_candidature(db_session, status="invalid")
        assert result == []

    def test_respects_limit(self, db_session, test_cv):
        for i in range(5):
            _make_analysis(db_session, test_cv, company=f"Co{i}")
        result = get_candidature(db_session, limit=3)
        assert len(result) == 3


class TestSearchCandidature:
    def test_finds_by_company(self, db_session, test_cv):
        _make_analysis(db_session, test_cv, company="Acme Corp")
        _make_analysis(db_session, test_cv, company="Other Inc")
        result = search_candidature(db_session, "acme")
        assert len(result) == 1
        assert result[0].company == "Acme Corp"

    def test_finds_by_role(self, db_session, test_cv):
        _make_analysis(db_session, test_cv, role="Backend Developer")
        _make_analysis(db_session, test_cv, role="Frontend Engineer")
        result = search_candidature(db_session, "backend")
        assert len(result) == 1

    def test_case_insensitive(self, db_session, test_cv):
        _make_analysis(db_session, test_cv, company="Google")
        result = search_candidature(db_session, "GOOGLE")
        assert len(result) == 1

    def test_no_match_returns_empty(self, db_session, test_cv):
        _make_analysis(db_session, test_cv, company="Alpha")
        result = search_candidature(db_session, "nonexistent")
        assert result == []


class TestGetTopCandidature:
    def test_returns_ordered_by_score(self, db_session, test_cv):
        _make_analysis(db_session, test_cv, score=50, company="Low")
        _make_analysis(db_session, test_cv, score=90, company="High")
        _make_analysis(db_session, test_cv, score=70, company="Mid")
        result = get_top_candidature(db_session, limit=3)
        scores = [a.score for a in result]
        assert scores == [90, 70, 50]

    def test_excludes_rejected(self, db_session, test_cv):
        _make_analysis(db_session, test_cv, score=95, status=AnalysisStatus.REJECTED)
        _make_analysis(db_session, test_cv, score=80, status=AnalysisStatus.APPLIED)
        result = get_top_candidature(db_session)
        assert len(result) == 1
        assert result[0].score == 80


class TestGetCandidatureByDateRange:
    def test_filters_by_date(self, db_session, test_cv):
        now = datetime.now(UTC)
        _make_analysis(db_session, test_cv, company="Recent")
        # Manually set created_at for the old one
        old = _make_analysis(db_session, test_cv, company="Old")
        old.created_at = now - timedelta(days=30)
        db_session.flush()

        result = get_candidature_by_date_range(
            db_session,
            now - timedelta(days=1),
            now + timedelta(days=1),
        )
        companies = [a.company for a in result]
        assert "Recent" in companies
        assert "Old" not in companies


class TestGetStaleCandidature:
    def test_finds_stale(self, db_session, test_cv):
        a = _make_analysis(db_session, test_cv, status=AnalysisStatus.APPLIED)
        a.applied_at = datetime.now(UTC) - timedelta(days=10)
        a.followed_up = False
        db_session.flush()

        result = get_stale_candidature(db_session, days=7)
        assert len(result) == 1

    def test_excludes_followed_up(self, db_session, test_cv):
        a = _make_analysis(db_session, test_cv, status=AnalysisStatus.APPLIED)
        a.applied_at = datetime.now(UTC) - timedelta(days=10)
        a.followed_up = True
        db_session.flush()

        result = get_stale_candidature(db_session, days=7)
        assert len(result) == 0

    def test_excludes_recent(self, db_session, test_cv):
        a = _make_analysis(db_session, test_cv, status=AnalysisStatus.APPLIED)
        a.applied_at = datetime.now(UTC) - timedelta(days=2)
        a.followed_up = False
        db_session.flush()

        result = get_stale_candidature(db_session, days=7)
        assert len(result) == 0


class TestSearchAllContacts:
    def test_finds_by_name(self, db_session):
        c = Contact(name="Marco Rossi", email="m@test.com", company="TestCo")
        db_session.add(c)
        db_session.flush()

        result = search_all_contacts(db_session, "marco")
        assert len(result) == 1

    def test_finds_by_company(self, db_session):
        c = Contact(name="Jane", email="j@test.com", company="Acme Corp")
        db_session.add(c)
        db_session.flush()

        result = search_all_contacts(db_session, "acme")
        assert len(result) == 1

    def test_finds_by_email(self, db_session):
        c = Contact(name="Jane", email="jane@special.com", company="Co")
        db_session.add(c)
        db_session.flush()

        result = search_all_contacts(db_session, "special")
        assert len(result) == 1

    def test_no_match(self, db_session):
        c = Contact(name="Jane", email="j@test.com", company="Co")
        db_session.add(c)
        db_session.flush()

        result = search_all_contacts(db_session, "nonexistent")
        assert result == []
