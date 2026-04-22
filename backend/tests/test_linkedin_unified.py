"""Tests for the unified metrics (JobAnalysis + LinkedIn) on the analytics snapshot."""

from datetime import UTC, datetime

from src.analytics.extractor import extract_features
from src.linkedin_import.models import LinkedinApplication
from src.linkedin_import.unified import (
    applications_by_month_unified,
    role_distribution_unified,
    total_volume_unified,
)


def _features_from_rows(rows):
    return [extract_features(r) for r in rows]


def _analysis_row(company, role, created_at=None, status="candidato"):
    return {
        "id": "x",
        "created_at": created_at,
        "applied_at": None,
        "status": status,
        "company": company,
        "role": role,
        "location": "remoto",
        "work_mode": "remote",
        "salary_info": None,
        "score": 70,
        "recommendation": "CONSIDER",
        "strengths": [],
        "gaps": [],
        "recruiter_info": {},
        "experience_required": {},
        "company_reputation": {},
        "career_track": None,
        "interviews": [],
    }


def _linkedin(db, company, title, date):
    db.add(
        LinkedinApplication(
            application_date=date,
            company_name=company,
            job_title=title,
            job_url=f"https://example/{company}/{title}",
        )
    )


def test_total_volume_counts_overlap_correctly(db_session):
    features = _features_from_rows(
        [
            _analysis_row("Acme", "DevOps Engineer"),
            _analysis_row("Beta", "Cloud Engineer"),
        ]
    )
    # One overlap (Acme + DevOps), one LinkedIn-only
    _linkedin(db_session, "acme", "DevOps Engineer", datetime(2025, 2, 1, tzinfo=UTC))
    _linkedin(db_session, "Globex", "Python Developer", datetime(2025, 3, 1, tzinfo=UTC))
    db_session.commit()

    v = total_volume_unified(db_session, features)
    assert v["job_analyses_count"] == 2
    assert v["linkedin_count"] == 2
    # Union of (acme, devops), (beta, cloud), (globex, backend/other-bucket) = 3
    assert v["unique_candidatures"] == 3
    assert v["overlap_count"] == 1


def test_role_distribution_merges_sources_deduped(db_session):
    features = _features_from_rows(
        [
            _analysis_row("Acme", "DevOps Engineer"),
            _analysis_row("Beta", "DevOps Engineer"),  # same bucket, diff company -> 2
        ]
    )
    # LinkedIn adds a third DevOps company + one Cloud company
    _linkedin(db_session, "Globex", "DevOps Engineer", datetime(2025, 2, 1, tzinfo=UTC))
    _linkedin(db_session, "Hooli", "Cloud Engineer", datetime(2025, 3, 1, tzinfo=UTC))
    # Duplicate — same (company, bucket) as existing JobAnalysis, must collapse
    _linkedin(db_session, "Acme", "DevOps engineer (ibrido)", datetime(2025, 4, 1, tzinfo=UTC))
    db_session.commit()

    dist = role_distribution_unified(db_session, features)
    # 3 unique DevOps companies (Acme, Beta, Globex) + 1 Cloud (Hooli)
    assert dist.get("devops") == 3
    assert dist.get("cloud") == 1


def test_applications_by_month_unified_sorted_and_deduped(db_session):
    features = _features_from_rows(
        [
            _analysis_row("Acme", "DevOps Engineer", created_at="2025-01-05T09:00:00+00:00"),
        ]
    )
    # Same (Acme, devops) from LinkedIn but one month later — must collapse
    # onto the earliest date (January)
    _linkedin(db_session, "Acme", "DevOps engineer", datetime(2025, 2, 10, tzinfo=UTC))
    # Distinct row in a new month
    _linkedin(db_session, "Globex", "Python Developer", datetime(2025, 3, 1, tzinfo=UTC))
    db_session.commit()

    months = applications_by_month_unified(db_session, features)
    # Two rows: 2025-01 (Acme collapsed onto earliest) + 2025-03 (Globex).
    # NO 2025-02 because Acme+Feb was dedup-collapsed with Acme+Jan.
    assert months == [
        {"month": "2025-01", "count": 1},
        {"month": "2025-03", "count": 1},
    ]


def test_empty_sources_return_zero_counts(db_session):
    v = total_volume_unified(db_session, [])
    assert v == {
        "job_analyses_count": 0,
        "linkedin_count": 0,
        "unique_candidatures": 0,
        "overlap_count": 0,
    }
    assert role_distribution_unified(db_session, []) == {}
    assert applications_by_month_unified(db_session, []) == []


def test_linkedin_only_data_still_feeds_metrics(db_session):
    # No JobAnalysis features, only LinkedIn — the unified view must not
    # drop these rows just because the cowork flow never saw them.
    _linkedin(db_session, "Acme", "DevOps Engineer", datetime(2025, 1, 1, tzinfo=UTC))
    _linkedin(db_session, "Beta", "Cloud Engineer", datetime(2025, 2, 1, tzinfo=UTC))
    db_session.commit()

    v = total_volume_unified(db_session, [])
    assert v["unique_candidatures"] == 2
    dist = role_distribution_unified(db_session, [])
    assert dist == {"devops": 1, "cloud": 1}


def test_rows_without_company_are_ignored(db_session):
    # JobAnalysis without company string must not count — dedup key is useless.
    features = _features_from_rows([_analysis_row("", "DevOps Engineer")])
    _linkedin(db_session, None, "DevOps Engineer", datetime(2025, 1, 1, tzinfo=UTC))
    db_session.commit()

    assert total_volume_unified(db_session, features)["unique_candidatures"] == 0
    assert role_distribution_unified(db_session, features) == {}
