"""Tests for analysis service."""

import uuid
from datetime import UTC

from src.analysis.models import AnalysisStatus, JobAnalysis
from src.analysis.service import (
    find_existing_analysis,
    get_analysis_by_id,
    get_recent_analyses,
    rebuild_result,
    update_status,
)


class TestFindExistingAnalysis:
    def test_returns_matching_analysis(self, db_session, test_analysis):
        result = find_existing_analysis(db_session, "abc123", "claude-haiku-4-5-20251001")
        assert result is not None
        assert result.id == test_analysis.id

    def test_returns_none_for_different_hash(self, db_session, test_analysis):
        result = find_existing_analysis(db_session, "different_hash", "claude-haiku-4-5-20251001")
        assert result is None

    def test_returns_none_for_different_model(self, db_session, test_analysis):
        result = find_existing_analysis(db_session, "abc123", "claude-sonnet-4-5-20250929")
        assert result is None


class TestRebuildResult:
    def test_rebuilds_basic_fields(self, test_analysis):
        result = rebuild_result(test_analysis)
        assert result["company"] == "TestCorp"
        assert result["role"] == "Software Engineer"
        assert result["score"] == 75
        assert result["recommendation"] == "CONSIDER"
        assert result["from_cache"] is False

    def test_rebuilds_jsonb_fields(self, test_analysis):
        result = rebuild_result(test_analysis)
        assert result["strengths"] == ["Python", "FastAPI", "SQL"]
        assert len(result["gaps"]) == 1
        assert result["gaps"][0]["gap"] == "Kubernetes"

    def test_from_cache_flag(self, test_analysis):
        result = rebuild_result(test_analysis, from_cache=True)
        assert result["from_cache"] is True

    def test_token_structure(self, test_analysis):
        result = rebuild_result(test_analysis)
        assert result["tokens"]["input"] == 1000
        assert result["tokens"]["output"] == 500
        assert result["tokens"]["total"] == 1500


class TestUpdateStatus:
    def test_updates_status(self, db_session, test_analysis):
        update_status(db_session, test_analysis, AnalysisStatus.APPLIED)
        db_session.flush()
        assert test_analysis.status == AnalysisStatus.APPLIED

    def test_sets_applied_at_on_candidato(self, db_session, test_analysis):
        assert test_analysis.applied_at is None
        update_status(db_session, test_analysis, AnalysisStatus.APPLIED)
        db_session.flush()
        assert test_analysis.applied_at is not None

    def test_does_not_overwrite_applied_at(self, db_session, test_analysis):
        from datetime import datetime

        original_date = datetime(2025, 1, 1, tzinfo=UTC)
        test_analysis.applied_at = original_date
        db_session.flush()

        update_status(db_session, test_analysis, AnalysisStatus.INTERVIEW)
        db_session.flush()
        assert test_analysis.applied_at == original_date

    def test_rejected_does_not_set_applied_at(self, db_session, test_analysis):
        update_status(db_session, test_analysis, AnalysisStatus.REJECTED)
        db_session.flush()
        assert test_analysis.applied_at is None


class TestGetAnalysisById:
    def test_finds_existing(self, db_session, test_analysis):
        result = get_analysis_by_id(db_session, str(test_analysis.id))
        assert result is not None
        assert result.company == "TestCorp"

    def test_returns_none_for_missing(self, db_session):
        result = get_analysis_by_id(db_session, str(uuid.uuid4()))
        assert result is None


class TestGetRecentAnalyses:
    def test_returns_analyses(self, db_session, test_analysis):
        results = get_recent_analyses(db_session)
        assert len(results) == 1

    def test_respects_limit(self, db_session, test_cv):
        for i in range(5):
            a = JobAnalysis(
                cv_id=test_cv.id,
                job_description=f"Job {i}",
                company=f"Company {i}",
                score=i * 20,
            )
            db_session.add(a)
        db_session.commit()

        results = get_recent_analyses(db_session, limit=3)
        assert len(results) == 3
