"""Tests for bulk-reject of stale da_valutare analyses.

Mirrors test_cleanup.py: verifies the query that targets PENDING rows older
than N days with score <= max_score, and that the transition to REJECTED is
applied only to matching candidates (never to APPLIED/INTERVIEW rows).
"""

import uuid
from datetime import UTC, datetime, timedelta

from src.analysis.models import AnalysisStatus, JobAnalysis


def _matches(db_session, days: int, max_score: int):
    cutoff = datetime.now(UTC) - timedelta(days=days)
    return (
        db_session.query(JobAnalysis)
        .filter(
            JobAnalysis.score <= max_score,
            JobAnalysis.created_at < cutoff,
            JobAnalysis.status == AnalysisStatus.PENDING,
        )
        .all()
    )


class TestBulkRejectPreview:
    def test_preview_counts_old_low_score_pending(self, db_session, test_cv):
        old = datetime.now(UTC) - timedelta(days=30)
        for _ in range(3):
            db_session.add(
                JobAnalysis(
                    id=uuid.uuid4(),
                    cv_id=test_cv.id,
                    job_description="x",
                    company="x",
                    score=50,
                    status=AnalysisStatus.PENDING,
                    created_at=old,
                )
            )
        db_session.commit()
        assert len(_matches(db_session, days=14, max_score=60)) == 3

    def test_preview_excludes_recent(self, db_session, test_cv):
        fresh = datetime.now(UTC) - timedelta(days=3)
        db_session.add(
            JobAnalysis(
                id=uuid.uuid4(),
                cv_id=test_cv.id,
                job_description="x",
                company="x",
                score=20,
                status=AnalysisStatus.PENDING,
                created_at=fresh,
            )
        )
        db_session.commit()
        assert _matches(db_session, days=14, max_score=60) == []

    def test_preview_excludes_high_score(self, db_session, test_cv):
        old = datetime.now(UTC) - timedelta(days=30)
        db_session.add(
            JobAnalysis(
                id=uuid.uuid4(),
                cv_id=test_cv.id,
                job_description="x",
                company="x",
                score=85,
                status=AnalysisStatus.PENDING,
                created_at=old,
            )
        )
        db_session.commit()
        assert _matches(db_session, days=14, max_score=60) == []


class TestBulkRejectTransition:
    def test_transitions_matching_rows_to_rejected(self, db_session, test_cv):
        old = datetime.now(UTC) - timedelta(days=30)
        ids = []
        for _ in range(2):
            a = JobAnalysis(
                id=uuid.uuid4(),
                cv_id=test_cv.id,
                job_description="x",
                company="x",
                score=40,
                status=AnalysisStatus.PENDING,
                created_at=old,
            )
            db_session.add(a)
            ids.append(a.id)
        db_session.commit()

        for a in _matches(db_session, days=14, max_score=60):
            a.status = AnalysisStatus.REJECTED.value
        db_session.commit()

        for aid in ids:
            a = db_session.query(JobAnalysis).filter(JobAnalysis.id == aid).one()
            assert a.status == AnalysisStatus.REJECTED.value

    def test_never_touches_applied_or_interview(self, db_session, test_cv):
        old = datetime.now(UTC) - timedelta(days=30)
        applied = JobAnalysis(
            id=uuid.uuid4(),
            cv_id=test_cv.id,
            job_description="x",
            company="applied",
            score=30,
            status=AnalysisStatus.APPLIED,
            created_at=old,
        )
        interview = JobAnalysis(
            id=uuid.uuid4(),
            cv_id=test_cv.id,
            job_description="x",
            company="interview",
            score=30,
            status=AnalysisStatus.INTERVIEW,
            created_at=old,
        )
        db_session.add_all([applied, interview])
        db_session.commit()

        matched = _matches(db_session, days=14, max_score=60)
        assert matched == []

        # Even if a caller tried to iterate and flip statuses, the query
        # guards against touching applied/interview rows.
        for a in matched:
            a.status = AnalysisStatus.REJECTED.value
        db_session.commit()

        assert db_session.query(JobAnalysis).filter(JobAnalysis.id == applied.id).one().status == (
            AnalysisStatus.APPLIED.value
        )
        assert db_session.query(JobAnalysis).filter(JobAnalysis.id == interview.id).one().status == (
            AnalysisStatus.INTERVIEW.value
        )
