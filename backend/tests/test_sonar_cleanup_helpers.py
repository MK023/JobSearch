"""Coverage for helpers extracted during the SonarCloud zero-out refactor.

These tests target the pure helpers that now slice up the previously
over-complex functions (python:S3776). They don't re-cover the network /
DB branches that the parent public functions hit — those are integration
concerns and stay exercised by the existing suites.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from src.analysis.service import _base_result
from src.batch.models import BatchItemStatus
from src.batch.service import (
    _item_dict,
    _item_preview,
    _overall_status,
    _status_key,
)
from src.integrations.glassdoor import (
    GlassdoorCache,
    _best_match,
    _build_glassdoor_url,
    _extract_sub_ratings,
    _is_reliable,
    _name_matches,
    _parse_cached,
    _parse_company,
    _percentage_or_none,
)
from src.integrations.news import _cached_articles_if_fresh
from src.integrations.salary import _cached_result_if_fresh

# ---------- glassdoor ----------


class TestGlassdoorReliability:
    def test_is_reliable_requires_rating_and_min_reviews(self) -> None:
        assert _is_reliable({"rating": 4.2, "review_count": 10})

    def test_is_reliable_rejects_low_review_count(self) -> None:
        assert not _is_reliable({"rating": 4.2, "review_count": 1})

    def test_is_reliable_rejects_missing_rating(self) -> None:
        assert not _is_reliable({"review_count": 10})

    def test_is_reliable_handles_missing_review_count(self) -> None:
        assert not _is_reliable({"rating": 4.2})


class TestGlassdoorNameMatches:
    def test_exact_match_case_insensitive(self) -> None:
        assert _name_matches({"name": "Acme Corp"}, "acme corp", "exact")

    def test_exact_no_match(self) -> None:
        assert not _name_matches({"name": "Acme"}, "acme corp", "exact")

    def test_prefix_match_when_result_starts_with_query(self) -> None:
        assert _name_matches({"name": "Acme Labs Italy"}, "acme labs", "prefix")

    def test_prefix_match_when_query_starts_with_result(self) -> None:
        assert _name_matches({"name": "Acme"}, "acme labs italy", "prefix")

    def test_contains_match(self) -> None:
        assert _name_matches({"name": "Big Acme Holdings"}, "acme", "contains")

    def test_missing_name_is_safe(self) -> None:
        assert not _name_matches({}, "acme", "exact")


class TestGlassdoorBestMatch:
    def test_returns_none_when_status_not_ok(self) -> None:
        assert _best_match({"status": "ERROR", "data": []}, "q") is None

    def test_returns_none_when_no_results(self) -> None:
        assert _best_match({"status": "OK", "data": []}, "q") is None

    def test_prefers_exact_over_prefix_over_contains(self) -> None:
        payload = {
            "status": "OK",
            "data": [
                {"name": "Giant Acme Holdings", "rating": 4.0, "review_count": 10},
                {"name": "Acme Corp", "rating": 4.5, "review_count": 20},
            ],
        }
        # Exact "acme corp" should win over "giant acme holdings" (contains)
        assert _best_match(payload, "Acme Corp")["name"] == "Acme Corp"

    def test_skips_results_without_enough_reviews(self) -> None:
        payload = {
            "status": "OK",
            "data": [
                {"name": "Acme Corp", "rating": 4.5, "review_count": 1},
            ],
        }
        assert _best_match(payload, "Acme Corp") is None


class TestGlassdoorParsers:
    def test_extract_sub_ratings_keeps_only_positive(self) -> None:
        out = _extract_sub_ratings(
            {
                "culture_and_values_rating": 4.1,
                "work_life_balance_rating": 0,
                "career_opportunities_rating": None,
                "senior_management_rating": 3.77,
            }
        )
        assert out == {"culture": 4.1, "senior_management": 3.8}

    def test_percentage_or_none_scales_fraction_to_int(self) -> None:
        assert _percentage_or_none({"ceo_rating": 0.87}, "ceo_rating") == 87

    def test_percentage_or_none_returns_none_on_zero(self) -> None:
        assert _percentage_or_none({"ceo_rating": 0}, "ceo_rating") is None

    def test_percentage_or_none_returns_none_when_missing(self) -> None:
        assert _percentage_or_none({}, "ceo_rating") is None

    def test_build_glassdoor_url_needs_company_id(self) -> None:
        assert _build_glassdoor_url({"name": "Acme", "company_id": ""}) == ""

    def test_build_glassdoor_url_slugifies_name(self) -> None:
        url = _build_glassdoor_url({"name": "Acme Corp", "company_id": "123"})
        assert "Working-at-Acme-Corp-EI_IE123.htm" in url

    def test_parse_company_shape(self) -> None:
        parsed = _parse_company(
            {
                "rating": 4.2,
                "review_count": 10,
                "ceo": "Jane Doe",
                "company_id": "77",
                "name": "Acme",
                "recommend_to_friend_rating": 0.9,
            }
        )
        assert parsed["glassdoor_rating"] == pytest.approx(4.2)
        assert parsed["review_count"] == 10
        assert parsed["ceo_name"] == "Jane Doe"
        assert parsed["recommend_to_friend"] == 90
        assert parsed["cached"] is False
        assert "Working-at-Acme-EI_IE77" in parsed["glassdoor_url"]

    def test_parse_cached_returns_none_for_empty_record(self) -> None:
        row = GlassdoorCache(company_name="acme", glassdoor_data="", rating=None)
        assert _parse_cached(row) is None

    def test_parse_cached_uses_stored_json(self) -> None:
        row = GlassdoorCache(
            company_name="acme",
            glassdoor_data='{"rating": 4.1, "review_count": 12, "name": "Acme"}',
        )
        out = _parse_cached(row)
        assert out is not None
        assert out["cached"] is True
        assert out["glassdoor_rating"] == pytest.approx(4.1)

    def test_parse_cached_falls_back_to_rating_column(self) -> None:
        row = GlassdoorCache(company_name="acme", glassdoor_data="not-json", rating=4.0, review_count=5)
        out = _parse_cached(row)
        assert out is not None
        assert out["cached"] is True
        assert out["review_count"] == 5


# ---------- news / salary cache freshness ----------


def _mk_row(fetched_at: datetime | None, data: str = '[{"title":"x"}]'):
    row = MagicMock()
    row.fetched_at = fetched_at
    row.news_data = data
    row.salary_data = data
    return row


class TestNewsCache:
    def test_cached_articles_fresh(self) -> None:
        row = _mk_row(datetime.now(UTC) - timedelta(days=1))
        articles = _cached_articles_if_fresh(row)
        assert articles == [{"title": "x"}]

    def test_cached_articles_stale(self) -> None:
        row = _mk_row(datetime.now(UTC) - timedelta(days=30))
        assert _cached_articles_if_fresh(row) is None

    def test_cached_articles_none_row(self) -> None:
        assert _cached_articles_if_fresh(None) is None

    def test_cached_articles_bad_json(self) -> None:
        row = _mk_row(datetime.now(UTC) - timedelta(days=1), data="not-json")
        assert _cached_articles_if_fresh(row) is None


class TestSalaryCache:
    def test_cached_result_fresh(self) -> None:
        row = _mk_row(datetime.now(UTC) - timedelta(days=5), data='{"median_salary": 50000}')
        out = _cached_result_if_fresh(row)
        assert out == {"median_salary": 50000}

    def test_cached_result_stale(self) -> None:
        row = _mk_row(datetime.now(UTC) - timedelta(days=45), data='{"x":1}')
        assert _cached_result_if_fresh(row) is None

    def test_cached_result_none(self) -> None:
        assert _cached_result_if_fresh(None) is None


# ---------- batch service helpers ----------


class TestBatchHelpers:
    def test_status_key_unwraps_enum(self) -> None:
        item = MagicMock()
        item.status = BatchItemStatus.DONE
        assert _status_key(item) == BatchItemStatus.DONE.value

    def test_status_key_passthrough_string(self) -> None:
        item = MagicMock()
        item.status = "something"
        # `hasattr(item.status, "value")` is False for a plain str
        assert _status_key(item) == "something"

    def test_item_preview_uses_stored_preview(self) -> None:
        item = MagicMock()
        item.preview = "hello"
        item.job_description = "unused"
        assert _item_preview(item) == "hello"

    def test_item_preview_truncates_description(self) -> None:
        item = MagicMock()
        item.preview = None
        item.job_description = "x" * 200
        out = _item_preview(item)
        assert out.endswith("...")
        assert len(out) == 83

    def test_item_preview_short_description(self) -> None:
        item = MagicMock()
        item.preview = None
        item.job_description = "brief"
        assert _item_preview(item) == "brief"

    def test_item_dict_shape(self) -> None:
        item = MagicMock()
        item.id = "id-1"
        item.status = BatchItemStatus.DONE
        item.preview = "p"
        item.job_description = "p"
        item.analysis_id = None
        item.error_message = None
        out = _item_dict(item, "done")
        assert out == {
            "id": "id-1",
            "status": "done",
            "preview": "p",
            "analysis_id": None,
            "error_message": None,
        }

    def test_overall_status_running(self) -> None:
        assert _overall_status({"running": 1, "done": 2}, 3) == "running"

    def test_overall_status_pending(self) -> None:
        assert _overall_status({"pending": 1, "done": 1}, 2) == "pending"

    def test_overall_status_error_when_no_done(self) -> None:
        assert _overall_status({"error": 1}, 1) == "error"

    def test_overall_status_error_ignored_when_some_done(self) -> None:
        assert _overall_status({"error": 1, "done": 2}, 3) == "done"

    def test_overall_status_empty(self) -> None:
        assert _overall_status({}, 0) == "empty"

    def test_overall_status_done_default(self) -> None:
        assert _overall_status({"done": 3}, 3) == "done"


# ---------- analysis.service._base_result ----------


class TestBaseResult:
    def test_falls_back_on_nulls(self) -> None:
        a = MagicMock()
        a.company = "Acme"
        a.role = "Dev"
        a.location = "Milan"
        a.work_mode = "remote"
        a.salary_info = None
        a.score = 80
        a.recommendation = "apply"
        a.job_summary = ""
        a.strengths = None
        a.gaps = None
        a.interview_scripts = None
        a.advice = None
        a.company_reputation = None
        a.salary_data = None
        a.company_news = None
        a.career_track = None
        a.track_reason = None
        a.benefits = None
        a.recruiter_info = None
        a.experience_required = None
        a.model_used = "haiku"
        a.tokens_input = 10
        a.tokens_output = 5
        a.cost_usd = 0.001
        out = _base_result(a, from_cache=True)
        assert out["strengths"] == []
        assert out["company_reputation"] == {}
        assert out["career_track"] == "hybrid_a_b"
        assert out["from_cache"] is True
        assert out["tokens"] == {"input": 10, "output": 5, "total": 15}


# ---------- interview/routes validators ----------


class TestInterviewValidators:
    def test_parse_datetime_field_accepts_iso_with_tz(self) -> None:
        from src.interview.routes import _parse_datetime_field

        parsed = _parse_datetime_field("2026-06-10T10:00:00+00:00")
        assert parsed is not None and parsed.tzinfo is not None

    def test_parse_datetime_field_assumes_utc_on_naive(self) -> None:
        from src.interview.routes import _parse_datetime_field

        parsed = _parse_datetime_field("2026-06-10T10:00:00")
        assert parsed is not None
        assert parsed.tzinfo == UTC

    def test_parse_datetime_field_rejects_garbage(self) -> None:
        from src.interview.routes import _parse_datetime_field

        assert _parse_datetime_field("not-a-date") is None

    def test_validate_payload_extras_happy(self) -> None:
        from src.interview.routes import InterviewPayload, _validate_payload_extras

        payload = InterviewPayload(
            scheduled_at="2026-06-10T10:00:00+00:00",
            platform="zoom",
            interview_type="tecnico",
            recruiter_email="jane@example.com",
            meeting_link="https://zoom.us/j/123",
        )
        assert _validate_payload_extras(payload) is None

    def test_validate_payload_extras_bad_platform(self) -> None:
        from src.interview.routes import InterviewPayload, _validate_payload_extras

        payload = InterviewPayload(scheduled_at="2026-06-10T10:00:00+00:00", platform="carrier-pigeon")
        resp = _validate_payload_extras(payload)
        assert resp is not None and resp.status_code == 400

    def test_validate_payload_extras_bad_interview_type(self) -> None:
        from src.interview.routes import InterviewPayload, _validate_payload_extras

        payload = InterviewPayload(scheduled_at="2026-06-10T10:00:00+00:00", interview_type="nope")
        resp = _validate_payload_extras(payload)
        assert resp is not None and resp.status_code == 400

    def test_validate_payload_extras_bad_email(self) -> None:
        from src.interview.routes import InterviewPayload, _validate_payload_extras

        payload = InterviewPayload(scheduled_at="2026-06-10T10:00:00+00:00", recruiter_email="not-an-email")
        resp = _validate_payload_extras(payload)
        assert resp is not None and resp.status_code == 400

    def test_validate_payload_extras_bad_meeting_link(self) -> None:
        from src.interview.routes import InterviewPayload, _validate_payload_extras

        payload = InterviewPayload(scheduled_at="2026-06-10T10:00:00+00:00", meeting_link="javascript:alert(1)")
        resp = _validate_payload_extras(payload)
        assert resp is not None and resp.status_code == 400

    def test_validate_schedule_rejects_past(self) -> None:
        from fastapi.responses import JSONResponse

        from src.interview.routes import InterviewPayload, _validate_schedule

        past = (datetime.now(UTC) - timedelta(days=2)).isoformat()
        payload = InterviewPayload(scheduled_at=past)
        result = _validate_schedule(payload)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_validate_schedule_rejects_ends_before_start(self) -> None:
        from fastapi.responses import JSONResponse

        from src.interview.routes import InterviewPayload, _validate_schedule

        start = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
        ends = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        payload = InterviewPayload(scheduled_at=start, ends_at=ends)
        result = _validate_schedule(payload)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_validate_schedule_happy(self) -> None:
        from src.interview.routes import InterviewPayload, _validate_schedule

        start = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        ends = (datetime.now(UTC) + timedelta(days=1, hours=1)).isoformat()
        payload = InterviewPayload(scheduled_at=start, ends_at=ends)
        result = _validate_schedule(payload)
        assert isinstance(result, tuple)
        scheduled, end = result
        assert scheduled.tzinfo is not None
        assert end is not None and end > scheduled
