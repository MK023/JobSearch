"""Integration tests: run_analytics() produces a snapshot that includes
LinkedIn import data alongside the existing JobAnalysis-derived metrics.

Covers the contract the template + downstream consumers rely on: one
snapshot is the single source of truth, no separate endpoint is needed.
"""

from datetime import UTC, datetime

from src.analysis.models import AnalysisStatus, JobAnalysis
from src.analytics_page.service import run_analytics
from src.linkedin_import.models import LinkedinApplication


def _add_analysis(db_session, test_cv, company="Acme", role="DevOps Engineer", status=AnalysisStatus.APPLIED):
    a = JobAnalysis(
        cv_id=test_cv.id,
        company=company,
        role=role,
        status=status,
        score=72,
        recommendation="CONSIDER",
        job_description="...",
        model_used="haiku",
        career_track="plan_a_devops",
    )
    db_session.add(a)
    return a


def test_run_analytics_includes_linkedin_section(db_session, test_cv, test_user):
    # Seed one JobAnalysis + one LinkedIn application
    _add_analysis(db_session, test_cv)
    db_session.add(
        LinkedinApplication(
            application_date=datetime(2026, 2, 10, tzinfo=UTC),
            company_name="Globex",
            job_title="Cloud Engineer",
            job_url="https://example.linkedin/jobs/view/1",
        )
    )
    db_session.commit()

    run = run_analytics(db_session, test_user.id)

    assert "linkedin_import" in run.snapshot
    li = run.snapshot["linkedin_import"]
    assert li["total_applications"] == 1
    assert li["unique_companies"] == 1
    assert li["first_application"] == "2026-02-10"
    assert li["applications_by_month"] == [{"month": "2026-02", "count": 1}]


def test_run_analytics_linkedin_section_empty_when_no_linkedin_data(db_session, test_cv, test_user):
    # Only JobAnalysis — no LinkedIn imports yet
    _add_analysis(db_session, test_cv)
    db_session.commit()

    run = run_analytics(db_session, test_user.id)

    assert "linkedin_import" in run.snapshot
    li = run.snapshot["linkedin_import"]
    assert li["total_applications"] == 0
    assert li["unique_companies"] == 0
    assert li["applications_by_month"] == []
    assert li["top_companies_without_analysis"] == []


def test_run_analytics_snapshot_preserves_existing_keys(db_session, test_cv, test_user):
    # Regression guard: adding linkedin_import must not remove any existing key
    # the frontend template already consumes.
    _add_analysis(db_session, test_cv, company="Acme", role="DevOps", status=AnalysisStatus.APPLIED)
    _add_analysis(db_session, test_cv, company="Beta", role="Cloud Engineer", status=AnalysisStatus.REJECTED)
    db_session.commit()

    run = run_analytics(db_session, test_user.id)

    expected_keys = {
        "counts_by_status",
        "role_distribution",
        "career_track_distribution",
        "conversion_by_role",
        "discriminant",
        "bias_signals",
        "total_features",
        "linkedin_import",  # new key, but the others must still be there
    }
    assert expected_keys.issubset(set(run.snapshot.keys()))
    assert run.snapshot["total_features"] == 2
