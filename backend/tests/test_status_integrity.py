"""Guard tests for job analysis status integrity.

These tests exist because a model/DB type mismatch (SQLEnum vs VARCHAR)
caused silent data loss in production — all 'candidato' statuses were
reset to 'da_valutare'. See migration 008 for the recovery.

DO NOT REMOVE THESE TESTS.
"""

import uuid

from sqlalchemy import String

from src.analysis.models import AnalysisStatus, JobAnalysis
from src.analysis.service import update_status


class TestStatusColumnType:
    """Ensure the status column type matches the DB schema (VARCHAR, not ENUM)."""

    def test_status_column_is_string_not_enum(self):
        """The status column MUST be String to match migration 001.

        If this test fails, someone changed the column type in the model
        without a corresponding migration — which caused data loss before.
        """
        col = JobAnalysis.__table__.columns["status"]
        assert isinstance(col.type, String), (
            f"status column must be String(20), not {type(col.type).__name__}. "
            "Changing this without a migration WILL cause data loss. "
            "See migration 008_recover_applied_status.py."
        )

    def test_status_default_is_da_valutare(self):
        """Default must match migration 001's default."""
        col = JobAnalysis.__table__.columns["status"]
        assert col.default.arg == "da_valutare"


class TestStatusTransitionIntegrity:
    """Ensure status changes always preserve applied_at."""

    def test_applied_sets_applied_at(self, db_session, test_analysis):
        assert test_analysis.applied_at is None
        update_status(db_session, test_analysis, AnalysisStatus.APPLIED)
        assert test_analysis.applied_at is not None
        assert test_analysis.status == AnalysisStatus.APPLIED.value

    def test_interview_sets_applied_at(self, db_session, test_analysis):
        update_status(db_session, test_analysis, AnalysisStatus.INTERVIEW)
        assert test_analysis.applied_at is not None

    def test_applied_at_not_overwritten_on_status_change(self, db_session, test_analysis):
        """Changing from candidato→colloquio must not reset applied_at."""
        update_status(db_session, test_analysis, AnalysisStatus.APPLIED)
        original_applied_at = test_analysis.applied_at

        update_status(db_session, test_analysis, AnalysisStatus.INTERVIEW)
        assert test_analysis.applied_at == original_applied_at

    def test_rejected_preserves_applied_at(self, db_session, test_analysis):
        """Rejecting a candidatura must not lose the applied_at timestamp."""
        update_status(db_session, test_analysis, AnalysisStatus.APPLIED)
        assert test_analysis.applied_at is not None

        update_status(db_session, test_analysis, AnalysisStatus.REJECTED)
        assert test_analysis.applied_at is not None


class TestStatusEnumValues:
    """Ensure enum values match what the DB stores."""

    def test_all_status_values_are_lowercase_italian(self):
        """DB stores these exact strings — changing them breaks existing data."""
        assert AnalysisStatus.PENDING.value == "da_valutare"
        assert AnalysisStatus.APPLIED.value == "candidato"
        assert AnalysisStatus.INTERVIEW.value == "colloquio"
        assert AnalysisStatus.OFFER.value == "offerta"
        assert AnalysisStatus.REJECTED.value == "scartato"

    def test_status_roundtrip(self, db_session, test_cv):
        """Write and read back each status to verify no silent conversion."""
        for status in AnalysisStatus:
            analysis = JobAnalysis(
                id=uuid.uuid4(),
                cv_id=test_cv.id,
                job_description="test",
                status=status.value,
            )
            db_session.add(analysis)
            db_session.flush()

            db_session.refresh(analysis)
            assert analysis.status == status.value, (
                f"Status roundtrip failed: wrote {status.value!r}, read back {analysis.status!r}"
            )
