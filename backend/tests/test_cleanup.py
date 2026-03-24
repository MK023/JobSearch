"""Tests for analysis cleanup and db-usage endpoint logic."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func

from src.analysis.models import AnalysisStatus, JobAnalysis
from src.audit.models import AuditLog
from src.batch.models import BatchItem
from src.batch.service import add_to_queue


class TestCleanupDryRun:
    """cleanup with dry_run=True returns count without deleting."""

    def test_dry_run_returns_count(self, db_session, test_cv):
        """Simulate dry_run: query for candidates, count them, don't delete."""
        # Create an old low-score PENDING analysis
        old_date = datetime.now(UTC) - timedelta(days=100)
        analysis = JobAnalysis(
            id=uuid.uuid4(),
            cv_id=test_cv.id,
            job_description="Old low-score job",
            company="OldCorp",
            score=20,
            status=AnalysisStatus.PENDING,
            created_at=old_date,
        )
        db_session.add(analysis)
        db_session.commit()

        # Simulate cleanup query with dry_run
        cutoff = datetime.now(UTC) - timedelta(days=90)
        candidates = (
            db_session.query(JobAnalysis)
            .filter(
                JobAnalysis.score <= 40,
                JobAnalysis.created_at < cutoff,
                JobAnalysis.status == AnalysisStatus.PENDING,
            )
            .all()
        )
        assert len(candidates) == 1

        # Dry run: don't delete
        assert db_session.query(JobAnalysis).count() >= 1

    def test_dry_run_does_not_delete(self, db_session, test_cv):
        old_date = datetime.now(UTC) - timedelta(days=100)
        analysis = JobAnalysis(
            id=uuid.uuid4(),
            cv_id=test_cv.id,
            job_description="Old job",
            company="Corp",
            score=30,
            status=AnalysisStatus.PENDING,
            created_at=old_date,
        )
        db_session.add(analysis)
        db_session.commit()
        count_before = db_session.query(JobAnalysis).count()

        # Simulate dry run: query but don't delete
        cutoff = datetime.now(UTC) - timedelta(days=90)
        candidates = (
            db_session.query(JobAnalysis)
            .filter(
                JobAnalysis.score <= 40,
                JobAnalysis.created_at < cutoff,
                JobAnalysis.status == AnalysisStatus.PENDING,
            )
            .all()
        )
        # dry_run: just count
        _ = len(candidates)
        assert db_session.query(JobAnalysis).count() == count_before


class TestCleanupActualDelete:
    """cleanup with dry_run=False actually deletes matching records."""

    def test_deletes_old_low_score_pending(self, db_session, test_cv):
        old_date = datetime.now(UTC) - timedelta(days=100)
        analysis = JobAnalysis(
            id=uuid.uuid4(),
            cv_id=test_cv.id,
            job_description="Old low-score job",
            company="OldCorp",
            score=20,
            status=AnalysisStatus.PENDING,
            created_at=old_date,
        )
        db_session.add(analysis)
        db_session.commit()

        cutoff = datetime.now(UTC) - timedelta(days=90)
        candidates = (
            db_session.query(JobAnalysis)
            .filter(
                JobAnalysis.score <= 40,
                JobAnalysis.created_at < cutoff,
                JobAnalysis.status == AnalysisStatus.PENDING,
            )
            .all()
        )
        assert len(candidates) == 1

        for a in candidates:
            db_session.delete(a)
        db_session.commit()

        remaining = db_session.query(JobAnalysis).filter(JobAnalysis.id == analysis.id).first()
        assert remaining is None

    def test_deletes_multiple_candidates(self, db_session, test_cv):
        old_date = datetime.now(UTC) - timedelta(days=120)
        for i in range(3):
            a = JobAnalysis(
                id=uuid.uuid4(),
                cv_id=test_cv.id,
                job_description=f"Old job {i}",
                company=f"Corp {i}",
                score=10 + i * 10,
                status=AnalysisStatus.PENDING,
                created_at=old_date,
            )
            db_session.add(a)
        db_session.commit()

        cutoff = datetime.now(UTC) - timedelta(days=90)
        candidates = (
            db_session.query(JobAnalysis)
            .filter(
                JobAnalysis.score <= 40,
                JobAnalysis.created_at < cutoff,
                JobAnalysis.status == AnalysisStatus.PENDING,
            )
            .all()
        )
        assert len(candidates) == 3

        for a in candidates:
            db_session.delete(a)
        db_session.commit()

        count = (
            db_session.query(func.count(JobAnalysis.id)).filter(JobAnalysis.status == AnalysisStatus.PENDING).scalar()
        )
        assert count == 0


class TestCleanupPreservesStatuses:
    """cleanup only deletes status=PENDING, preserves APPLIED, INTERVIEW, REJECTED."""

    def test_preserves_applied(self, db_session, test_cv):
        old_date = datetime.now(UTC) - timedelta(days=100)
        analysis = JobAnalysis(
            id=uuid.uuid4(),
            cv_id=test_cv.id,
            job_description="Applied job",
            company="GoodCorp",
            score=30,
            status=AnalysisStatus.APPLIED,
            created_at=old_date,
        )
        db_session.add(analysis)
        db_session.commit()

        cutoff = datetime.now(UTC) - timedelta(days=90)
        candidates = (
            db_session.query(JobAnalysis)
            .filter(
                JobAnalysis.score <= 40,
                JobAnalysis.created_at < cutoff,
                JobAnalysis.status == AnalysisStatus.PENDING,
            )
            .all()
        )
        assert len(candidates) == 0

    def test_preserves_interview(self, db_session, test_cv):
        old_date = datetime.now(UTC) - timedelta(days=100)
        analysis = JobAnalysis(
            id=uuid.uuid4(),
            cv_id=test_cv.id,
            job_description="Interview job",
            company="GreatCorp",
            score=25,
            status=AnalysisStatus.INTERVIEW,
            created_at=old_date,
        )
        db_session.add(analysis)
        db_session.commit()

        cutoff = datetime.now(UTC) - timedelta(days=90)
        candidates = (
            db_session.query(JobAnalysis)
            .filter(
                JobAnalysis.score <= 40,
                JobAnalysis.created_at < cutoff,
                JobAnalysis.status == AnalysisStatus.PENDING,
            )
            .all()
        )
        assert len(candidates) == 0

    def test_preserves_rejected(self, db_session, test_cv):
        old_date = datetime.now(UTC) - timedelta(days=100)
        analysis = JobAnalysis(
            id=uuid.uuid4(),
            cv_id=test_cv.id,
            job_description="Rejected job",
            company="BadCorp",
            score=15,
            status=AnalysisStatus.REJECTED,
            created_at=old_date,
        )
        db_session.add(analysis)
        db_session.commit()

        cutoff = datetime.now(UTC) - timedelta(days=90)
        candidates = (
            db_session.query(JobAnalysis)
            .filter(
                JobAnalysis.score <= 40,
                JobAnalysis.created_at < cutoff,
                JobAnalysis.status == AnalysisStatus.PENDING,
            )
            .all()
        )
        assert len(candidates) == 0

    def test_mixed_statuses_only_deletes_pending(self, db_session, test_cv):
        old_date = datetime.now(UTC) - timedelta(days=100)
        statuses = [
            (AnalysisStatus.PENDING, "Pending Corp"),
            (AnalysisStatus.APPLIED, "Applied Corp"),
            (AnalysisStatus.INTERVIEW, "Interview Corp"),
            (AnalysisStatus.REJECTED, "Rejected Corp"),
        ]
        for status, company in statuses:
            a = JobAnalysis(
                id=uuid.uuid4(),
                cv_id=test_cv.id,
                job_description=f"Job at {company}",
                company=company,
                score=20,
                status=status,
                created_at=old_date,
            )
            db_session.add(a)
        db_session.commit()

        cutoff = datetime.now(UTC) - timedelta(days=90)
        candidates = (
            db_session.query(JobAnalysis)
            .filter(
                JobAnalysis.score <= 40,
                JobAnalysis.created_at < cutoff,
                JobAnalysis.status == AnalysisStatus.PENDING,
            )
            .all()
        )
        assert len(candidates) == 1
        assert candidates[0].company == "Pending Corp"

        for a in candidates:
            db_session.delete(a)
        db_session.commit()

        remaining = db_session.query(JobAnalysis).count()
        assert remaining == 3  # applied, interview, rejected preserved


class TestCleanupFilters:
    """cleanup respects days and max_score filters."""

    def test_respects_days_filter(self, db_session, test_cv):
        """Items newer than the cutoff should NOT be deleted."""
        recent_date = datetime.now(UTC) - timedelta(days=30)
        analysis = JobAnalysis(
            id=uuid.uuid4(),
            cv_id=test_cv.id,
            job_description="Recent low-score job",
            company="NewCorp",
            score=20,
            status=AnalysisStatus.PENDING,
            created_at=recent_date,
        )
        db_session.add(analysis)
        db_session.commit()

        cutoff = datetime.now(UTC) - timedelta(days=90)
        candidates = (
            db_session.query(JobAnalysis)
            .filter(
                JobAnalysis.score <= 40,
                JobAnalysis.created_at < cutoff,
                JobAnalysis.status == AnalysisStatus.PENDING,
            )
            .all()
        )
        assert len(candidates) == 0

    def test_respects_max_score_filter(self, db_session, test_cv):
        """Items with score above max_score should NOT be deleted."""
        old_date = datetime.now(UTC) - timedelta(days=100)
        analysis = JobAnalysis(
            id=uuid.uuid4(),
            cv_id=test_cv.id,
            job_description="Old high-score job",
            company="TopCorp",
            score=80,
            status=AnalysisStatus.PENDING,
            created_at=old_date,
        )
        db_session.add(analysis)
        db_session.commit()

        cutoff = datetime.now(UTC) - timedelta(days=90)
        candidates = (
            db_session.query(JobAnalysis)
            .filter(
                JobAnalysis.score <= 40,
                JobAnalysis.created_at < cutoff,
                JobAnalysis.status == AnalysisStatus.PENDING,
            )
            .all()
        )
        assert len(candidates) == 0

    def test_custom_days_and_max_score(self, db_session, test_cv):
        """Verify that both filters work together with custom values."""
        old_date = datetime.now(UTC) - timedelta(days=200)

        # score=50, should be included with max_score=60
        a1 = JobAnalysis(
            id=uuid.uuid4(),
            cv_id=test_cv.id,
            job_description="Job 1",
            company="Corp1",
            score=50,
            status=AnalysisStatus.PENDING,
            created_at=old_date,
        )
        # score=70, should be excluded with max_score=60
        a2 = JobAnalysis(
            id=uuid.uuid4(),
            cv_id=test_cv.id,
            job_description="Job 2",
            company="Corp2",
            score=70,
            status=AnalysisStatus.PENDING,
            created_at=old_date,
        )
        db_session.add_all([a1, a2])
        db_session.commit()

        days = 180
        max_score = 60
        cutoff = datetime.now(UTC) - timedelta(days=days)
        candidates = (
            db_session.query(JobAnalysis)
            .filter(
                JobAnalysis.score <= max_score,
                JobAnalysis.created_at < cutoff,
                JobAnalysis.status == AnalysisStatus.PENDING,
            )
            .all()
        )
        assert len(candidates) == 1
        assert candidates[0].company == "Corp1"


class TestDbUsage:
    """Test the db_usage query logic (counts and size estimation)."""

    def test_returns_correct_analysis_count(self, db_session, test_analysis):
        count = db_session.query(func.count(JobAnalysis.id)).scalar() or 0
        assert count == 1

    def test_returns_correct_batch_count(self, db_session, test_cv):
        add_to_queue(db_session, test_cv.id, "Job 1", cv_text="test cv")
        add_to_queue(db_session, test_cv.id, "Job 2", cv_text="test cv")
        db_session.commit()

        count = db_session.query(func.count(BatchItem.id)).scalar() or 0
        assert count == 2

    def test_returns_correct_audit_count(self, db_session, test_user):
        log = AuditLog(
            id=uuid.uuid4(),
            user_id=test_user.id,
            action="test_action",
            detail="test detail",
        )
        db_session.add(log)
        db_session.commit()

        count = db_session.query(func.count(AuditLog.id)).scalar() or 0
        assert count == 1

    def test_empty_db_returns_zero_counts(self, db_session):
        analyses_count = db_session.query(func.count(JobAnalysis.id)).scalar() or 0
        batch_items_count = db_session.query(func.count(BatchItem.id)).scalar() or 0
        audit_logs_count = db_session.query(func.count(AuditLog.id)).scalar() or 0

        assert analyses_count == 0
        assert batch_items_count == 0
        assert audit_logs_count == 0

    def test_estimated_size_calculation(self, db_session, test_analysis, test_cv):
        add_to_queue(db_session, test_cv.id, "Job 1", cv_text="test cv")
        db_session.commit()

        analyses_count = db_session.query(func.count(JobAnalysis.id)).scalar() or 0
        batch_items_count = db_session.query(func.count(BatchItem.id)).scalar() or 0
        audit_logs_count = db_session.query(func.count(AuditLog.id)).scalar() or 0

        # Same formula as in dashboard/routes.py
        estimated_size_mb = round(
            (analyses_count * 50 + batch_items_count * 5 + audit_logs_count * 1) / 1024,
            1,
        )
        assert estimated_size_mb > 0
        assert analyses_count == 1
        assert batch_items_count == 1
