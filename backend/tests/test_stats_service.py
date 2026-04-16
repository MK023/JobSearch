"""Integration tests for the stats aggregator.

Every test runs against the SQLite fixture `db_session` (integration-level):
no mocks of the session, no MagicMock. Seed the DB with real rows and
assert on the aggregate output.
"""

import uuid
from datetime import UTC, datetime, timedelta

from src.analysis.models import AnalysisStatus, JobAnalysis
from src.cover_letter.models import CoverLetter
from src.stats.service import (
    applications_per_week,
    contract_split,
    funnel_counts,
    get_stats,
    recommendation_split,
    score_by_status,
    score_distribution,
    spending_timeline,
    top_companies,
    work_mode_split,
)


def _make(db_session, test_cv, **overrides):
    defaults = {
        "id": uuid.uuid4(),
        "cv_id": test_cv.id,
        "job_description": "job",
        "company": "Acme",
        "role": "Engineer",
        "score": 70,
        "status": AnalysisStatus.APPLIED.value,
        "recommendation": "APPLY",
        "work_mode": "remoto",
        "cost_usd": 0.01,
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    row = JobAnalysis(**defaults)
    db_session.add(row)
    db_session.commit()
    return row


class TestFunnelCounts:
    def test_empty_db(self, db_session):
        assert funnel_counts(db_session) == {
            "da_valutare": 0,
            "candidato": 0,
            "colloquio": 0,
            "offerta": 0,
            "scartato": 0,
        }

    def test_counts_each_status(self, db_session, test_cv):
        _make(db_session, test_cv, status=AnalysisStatus.PENDING.value)
        _make(db_session, test_cv, status=AnalysisStatus.APPLIED.value)
        _make(db_session, test_cv, status=AnalysisStatus.APPLIED.value)
        _make(db_session, test_cv, status=AnalysisStatus.INTERVIEW.value)
        _make(db_session, test_cv, status=AnalysisStatus.OFFER.value)
        _make(db_session, test_cv, status=AnalysisStatus.REJECTED.value)

        f = funnel_counts(db_session)
        assert f == {
            "da_valutare": 1,
            "candidato": 2,
            "colloquio": 1,
            "offerta": 1,
            "scartato": 1,
        }


class TestScoreDistribution:
    def test_bins_and_exclusions(self, db_session, test_cv):
        # These three count: APPLIED/INTERVIEW/OFFER
        _make(db_session, test_cv, score=5, status=AnalysisStatus.APPLIED.value)
        _make(db_session, test_cv, score=55, status=AnalysisStatus.INTERVIEW.value)
        _make(db_session, test_cv, score=85, status=AnalysisStatus.OFFER.value)
        # These two do NOT count (PENDING + REJECTED)
        _make(db_session, test_cv, score=90, status=AnalysisStatus.PENDING.value)
        _make(db_session, test_cv, score=90, status=AnalysisStatus.REJECTED.value)

        bins = {row["bin"]: row["count"] for row in score_distribution(db_session)}
        assert bins["0-19"] == 1
        assert bins["40-59"] == 1
        assert bins["80-100"] == 1
        assert bins["20-39"] == 0
        assert bins["60-79"] == 0


class TestTopCompanies:
    def test_ranking_and_exclude_empty(self, db_session, test_cv):
        for _ in range(3):
            _make(db_session, test_cv, company="Acme")
        for _ in range(2):
            _make(db_session, test_cv, company="Widgets")
        _make(db_session, test_cv, company="")  # excluded
        _make(db_session, test_cv, company=None)  # excluded

        top = top_companies(db_session, limit=5)
        assert top[0] == {"company": "Acme", "count": 3}
        assert top[1] == {"company": "Widgets", "count": 2}
        assert all(row["company"] for row in top)


class TestWorkModeSplit:
    def test_split_with_empty_fallback(self, db_session, test_cv):
        _make(db_session, test_cv, work_mode="remoto")
        _make(db_session, test_cv, work_mode="remoto")
        _make(db_session, test_cv, work_mode="ibrido")
        _make(db_session, test_cv, work_mode="")

        result = {row["mode"]: row["count"] for row in work_mode_split(db_session)}
        assert result["remoto"] == 2
        assert result["ibrido"] == 1
        assert result["non specificato"] == 1


class TestContractSplit:
    def test_buckets(self, db_session, test_cv):
        _make(
            db_session, test_cv, recruiter_info={"is_body_rental": True, "is_freelance": False, "is_recruiter": False}
        )
        _make(
            db_session, test_cv, recruiter_info={"is_body_rental": False, "is_freelance": True, "is_recruiter": False}
        )
        _make(
            db_session, test_cv, recruiter_info={"is_body_rental": False, "is_freelance": False, "is_recruiter": True}
        )
        _make(
            db_session, test_cv, recruiter_info={"is_body_rental": False, "is_freelance": False, "is_recruiter": False}
        )
        _make(db_session, test_cv, recruiter_info=None)

        split = contract_split(db_session)
        assert split["body_rental"] == 1
        assert split["freelance"] == 1
        assert split["recruiter_esterno"] == 1
        # Dipendente = total - body_rental - freelance = 5 - 1 - 1 = 3
        assert split["dipendente"] == 3


class TestRecommendationSplit:
    def test_normalization(self, db_session, test_cv):
        _make(db_session, test_cv, recommendation="APPLY")
        _make(db_session, test_cv, recommendation="apply")  # lowercase → uppercase key
        _make(db_session, test_cv, recommendation="CONSIDER")
        _make(db_session, test_cv, recommendation="SKIP")
        _make(db_session, test_cv, recommendation="???")  # → ALTRO

        r = recommendation_split(db_session)
        assert r["APPLY"] == 2
        assert r["CONSIDER"] == 1
        assert r["SKIP"] == 1
        assert r["ALTRO"] == 1


class TestApplicationsPerWeek:
    def test_last_weeks_only(self, db_session, test_cv):
        recent = datetime.now(UTC) - timedelta(days=2)
        old = datetime.now(UTC) - timedelta(weeks=20)
        _make(db_session, test_cv, created_at=recent, status=AnalysisStatus.APPLIED.value)
        _make(db_session, test_cv, created_at=old, status=AnalysisStatus.APPLIED.value)

        rows = applications_per_week(db_session, weeks=12)
        # Old row must be filtered out by the cutoff
        total = sum(r["count"] for r in rows)
        assert total == 1


class TestSpendingTimeline:
    def test_sums_analysis_and_cover_letter(self, db_session, test_cv):
        today = datetime.now(UTC)
        a = _make(db_session, test_cv, cost_usd=0.10, created_at=today)
        cl = CoverLetter(
            id=uuid.uuid4(),
            analysis_id=a.id,
            language="italiano",
            content="...",
            cost_usd=0.05,
            tokens_input=10,
            tokens_output=10,
            created_at=today,
        )
        db_session.add(cl)
        db_session.commit()

        rows = spending_timeline(db_session, days=30)
        assert len(rows) == 1
        assert round(rows[0]["cost_usd"], 5) == 0.15


class TestScoreByStatus:
    def test_avg_per_status(self, db_session, test_cv):
        _make(db_session, test_cv, score=60, status=AnalysisStatus.APPLIED.value)
        _make(db_session, test_cv, score=80, status=AnalysisStatus.APPLIED.value)
        _make(db_session, test_cv, score=40, status=AnalysisStatus.REJECTED.value)

        rows = {row["status"]: row for row in score_by_status(db_session)}
        assert rows["candidato"]["avg_score"] == 70.0
        assert rows["candidato"]["count"] == 2
        assert rows["scartato"]["avg_score"] == 40.0


class TestGetStatsFull:
    def test_full_payload_keys(self, db_session):
        payload = get_stats(db_session)
        for key in [
            "funnel",
            "score_distribution",
            "applications_per_week",
            "top_companies",
            "work_mode_split",
            "contract_split",
            "recommendation_split",
            "spending_timeline",
            "score_by_status",
            "generated_at",
        ]:
            assert key in payload

    def test_uses_cache_when_provided(self, db_session):
        class MemCache:
            def __init__(self):
                self.store = {}

            def get_json(self, key):
                return self.store.get(key)

            def set_json(self, key, data, ttl):
                self.store[key] = data

            def get(self, key):  # noqa: ARG002
                return None

            def set(self, key, value, ttl):  # noqa: ARG002
                pass

            def stats(self):
                return {"hits": 0, "misses": 0, "errors": 0}

        cache = MemCache()
        p1 = get_stats(db_session, cache=cache)
        p2 = get_stats(db_session, cache=cache)
        # Same object round-trip via cache
        assert p1 == p2
        assert len(cache.store) == 1
