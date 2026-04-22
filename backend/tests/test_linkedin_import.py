"""Tests for the LinkedIn applications import + summary endpoint."""

from datetime import UTC, datetime

from src.analysis.models import AnalysisStatus, JobAnalysis
from src.linkedin_import.models import LinkedinApplication
from src.linkedin_import.service import get_summary


def _make_app(db_session, company, title, url, d, **extra):
    row = LinkedinApplication(
        application_date=d,
        company_name=company,
        job_title=title,
        job_url=url,
        **extra,
    )
    db_session.add(row)
    return row


def test_summary_empty_db(db_session):
    s = get_summary(db_session)
    assert s["total_applications"] == 0
    assert s["unique_companies"] == 0
    assert s["first_application"] is None
    assert s["last_application"] is None
    assert s["applications_by_month"] == []
    assert s["top_companies_without_analysis"] == []


def test_summary_counts_and_dates(db_session):
    _make_app(db_session, "Acme", "DevOps Engineer", "u1", datetime(2025, 1, 5, tzinfo=UTC))
    _make_app(db_session, "Acme", "DevOps Engineer 2", "u2", datetime(2025, 2, 10, tzinfo=UTC))
    _make_app(db_session, "Globex", "Cloud Engineer", "u3", datetime(2025, 3, 15, tzinfo=UTC))
    db_session.commit()

    s = get_summary(db_session)
    assert s["total_applications"] == 3
    assert s["unique_companies"] == 2
    assert s["first_application"] == "2025-01-05"
    assert s["last_application"] == "2025-03-15"


def test_summary_monthly_aggregation(db_session):
    _make_app(db_session, "A", "t1", "u1", datetime(2025, 1, 5, tzinfo=UTC))
    _make_app(db_session, "A", "t2", "u2", datetime(2025, 1, 20, tzinfo=UTC))
    _make_app(db_session, "A", "t3", "u3", datetime(2025, 2, 1, tzinfo=UTC))
    db_session.commit()

    months = get_summary(db_session)["applications_by_month"]
    # Oldest -> newest, labels YYYY-MM
    assert months == [{"month": "2025-01", "count": 2}, {"month": "2025-02", "count": 1}]


def test_summary_filters_out_companies_already_analysed(db_session, test_cv):
    # "Acme" has BOTH a LinkedIn application and a job_analyses row -> not dark
    db_session.add(
        JobAnalysis(
            cv_id=test_cv.id,
            company="Acme",
            role="DevOps Engineer",
            status=AnalysisStatus.APPLIED,
            score=70,
            recommendation="CONSIDER",
            job_description="...",
            model_used="haiku",
        )
    )
    _make_app(db_session, "Acme", "DevOps Engineer", "u1", datetime(2025, 1, 5, tzinfo=UTC))
    # "Globex" only in LinkedIn applications -> dark
    _make_app(db_session, "Globex", "Cloud Engineer", "u2", datetime(2025, 2, 10, tzinfo=UTC))
    _make_app(db_session, "Globex", "SRE", "u3", datetime(2025, 3, 12, tzinfo=UTC))
    db_session.commit()

    dark = get_summary(db_session)["top_companies_without_analysis"]
    # Only Globex shows up
    assert len(dark) == 1
    assert dark[0]["company"] == "globex"
    assert dark[0]["count"] == 2
    assert dark[0]["first_apply"] == "2025-02-10"
    assert dark[0]["last_apply"] == "2025-03-12"


def test_summary_trims_and_lowercases_company_names_in_dark_filter(db_session, test_cv):
    # An analysed company stored with different case/whitespace must still
    # suppress the LinkedIn row from the "dark" list.
    db_session.add(
        JobAnalysis(
            cv_id=test_cv.id,
            company=" Acme ",
            role="DevOps",
            status=AnalysisStatus.APPLIED,
            score=70,
            recommendation="CONSIDER",
            job_description="...",
            model_used="haiku",
        )
    )
    _make_app(db_session, "ACME", "DevOps", "u1", datetime(2025, 1, 5, tzinfo=UTC))
    _make_app(db_session, "acme", "SRE", "u2", datetime(2025, 2, 1, tzinfo=UTC))
    db_session.commit()

    dark = get_summary(db_session)["top_companies_without_analysis"]
    assert dark == []


def test_summary_ignores_null_application_date_in_monthly_rollup(db_session):
    _make_app(db_session, "A", "t1", "u1", datetime(2025, 1, 5, tzinfo=UTC))
    _make_app(db_session, "A", "t2", "u2", None)  # should be skipped
    db_session.commit()

    months = get_summary(db_session)["applications_by_month"]
    assert months == [{"month": "2025-01", "count": 1}]
