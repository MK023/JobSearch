"""Coverage for helpers extracted during the SonarCloud zero-out refactor.

These tests target the pure helpers that now slice up the previously
over-complex functions (python:S3776). They don't re-cover the network /
DB branches that the parent public functions hit — those are integration
concerns and stay exercised by the existing suites.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.analysis.service import _base_result
from src.batch.models import BatchItem, BatchItemStatus
from src.batch.routes import _serialize_batch_result
from src.batch.service import (
    _execute_analysis,
    _item_dict,
    _item_preview,
    _mark_items_error,
    _overall_status,
    _process_one_item,
    _record_failure,
    _record_success,
    _status_key,
    _try_skip_dedup,
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
    _try_db_cache,
    _try_redis_cache,
)
from src.integrations.news import (
    NewsCache,
    _cached_articles_if_fresh,
)
from src.integrations.news import (
    _load_cached_row as _news_load_cached_row,
)
from src.integrations.news import (
    _upsert_cache as _news_upsert_cache,
)
from src.integrations.salary import (
    SalaryCache,
    _cached_result_if_fresh,
)
from src.integrations.salary import (
    _load_cached_row as _salary_load_cached_row,
)
from src.integrations.salary import (
    _upsert_cache as _salary_upsert_cache,
)
from src.notifications.document_reminder import (
    _group_files_by_interview,
    _preload_already_notified,
    _send_reminder_email,
)
from src.read_routes import _analysis_export_row, _interview_export_row

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


# ---------- glassdoor: Redis + DB cache tier helpers ----------


class TestGlassdoorCacheTiers:
    def test_try_redis_cache_none_when_no_cache(self) -> None:
        assert _try_redis_cache(None, "k") is None

    def test_try_redis_cache_none_on_miss(self) -> None:
        cache = MagicMock()
        cache.get_json.return_value = None
        assert _try_redis_cache(cache, "k") is None

    def test_try_redis_cache_hit_marks_cached(self) -> None:
        cache = MagicMock()
        cache.get_json.return_value = {"glassdoor_rating": 4.0}
        out = _try_redis_cache(cache, "k")
        assert out is not None and out["cached"] is True

    def test_try_db_cache_miss_when_no_row(self) -> None:
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        assert _try_db_cache(db, "acme", None, "k") is None

    def test_try_db_cache_returns_none_when_stale(self) -> None:
        row = GlassdoorCache(
            company_name="acme",
            glassdoor_data='{"rating":4.0,"review_count":10,"name":"Acme"}',
            rating=4.0,
            review_count=10,
        )
        row.fetched_at = datetime.now(UTC) - timedelta(days=60)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = row
        assert _try_db_cache(db, "acme", None, "k") is None

    def test_try_db_cache_warms_redis_on_hit(self) -> None:
        row = GlassdoorCache(
            company_name="acme",
            glassdoor_data='{"rating":4.0,"review_count":10,"name":"Acme"}',
            rating=4.0,
            review_count=10,
        )
        row.fetched_at = datetime.now(UTC) - timedelta(days=1)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = row
        cache = MagicMock()
        out = _try_db_cache(db, "acme", cache, "k")
        assert out is not None
        cache.set_json.assert_called_once()


# ---------- news/salary cache row loaders + upsert ----------


class TestNewsSalaryCacheLoaders:
    def test_news_load_cached_row_swallows_errors(self) -> None:
        db = MagicMock()
        db.query.side_effect = RuntimeError("down")
        assert _news_load_cached_row(db, "acme") is None

    def test_news_upsert_cache_inserts_when_no_cached(self) -> None:
        db = MagicMock()
        _news_upsert_cache(db, "acme", None, [{"title": "x"}])
        db.add.assert_called_once()
        db.flush.assert_called_once()

    def test_news_upsert_cache_updates_existing_row(self) -> None:
        db = MagicMock()
        row = NewsCache(company_name="acme")
        _news_upsert_cache(db, "acme", row, [{"title": "y"}])
        assert "title" in str(row.news_data)
        db.add.assert_not_called()

    def test_news_upsert_cache_swallows_db_errors(self) -> None:
        db = MagicMock()
        db.add.side_effect = RuntimeError("db down")
        # Should NOT raise
        _news_upsert_cache(db, "acme", None, [{"title": "x"}])

    def test_salary_load_cached_row_swallows_errors(self) -> None:
        db = MagicMock()
        db.query.side_effect = RuntimeError("down")
        assert _salary_load_cached_row(db, "k") is None

    def test_salary_upsert_cache_inserts_new(self) -> None:
        db = MagicMock()
        _salary_upsert_cache(db, "k", None, {"median_salary": 1})
        db.add.assert_called_once()

    def test_salary_upsert_cache_updates_existing(self) -> None:
        db = MagicMock()
        row = SalaryCache(cache_key="k")
        _salary_upsert_cache(db, "k", row, {"median_salary": 2})
        assert "median_salary" in str(row.salary_data)

    def test_salary_upsert_cache_swallows_flush_errors(self) -> None:
        db = MagicMock()
        db.flush.side_effect = RuntimeError("oops")
        _salary_upsert_cache(db, "k", None, {"median_salary": 3})  # no raise


# ---------- batch.service helpers (mark/record/process) ----------


def _fake_batch_item(**overrides) -> MagicMock:
    item = MagicMock(spec=BatchItem)
    item.id = "item-1"
    item.status = BatchItemStatus.PENDING
    item.preview = "preview"
    item.job_description = "job"
    item.job_url = "https://j.example"
    item.content_hash = "0123456789abcdef"
    item.model = "haiku"
    item.attempt_count = 0
    item.error_message = None
    item.analysis_id = None
    for k, v in overrides.items():
        setattr(item, k, v)
    return item


class TestBatchProcessingHelpers:
    def test_mark_items_error_sets_all(self) -> None:
        db = MagicMock()
        items = [_fake_batch_item(), _fake_batch_item()]
        _mark_items_error(db, items, "No CV")
        for it in items:
            assert it.error_message == "No CV"
        db.commit.assert_called_once()

    def test_try_skip_dedup_no_existing(self) -> None:
        db = MagicMock()
        item = _fake_batch_item()
        with patch("src.batch.service.find_existing_analysis", return_value=None):
            assert _try_skip_dedup(db, item, "0123abcd") is False

    def test_try_skip_dedup_marks_skipped(self) -> None:
        db = MagicMock()
        item = _fake_batch_item()
        existing = MagicMock()
        existing.id = "abc"
        with patch("src.batch.service.find_existing_analysis", return_value=existing):
            assert _try_skip_dedup(db, item, "0123abcd") is True
        assert item.analysis_id == "abc"
        db.commit.assert_called_once()

    def test_execute_analysis_raises_timeout(self) -> None:
        import time as _t
        from concurrent.futures import ThreadPoolExecutor

        item = _fake_batch_item()
        cv = MagicMock()
        cv.raw_text = "cv"
        cv.id = "cv-uuid"

        def _slow(*_a, **_kw):
            _t.sleep(0.2)
            return (MagicMock(), {})

        with (
            ThreadPoolExecutor(max_workers=1) as executor,
            patch("src.batch.service._BATCH_ITEM_TIMEOUT", 0.01),
            patch("src.batch.service.run_analysis", side_effect=_slow),
            pytest.raises(TimeoutError),
        ):
            _execute_analysis(executor, MagicMock(), item, cv, None, "u")

    def test_record_success_commits_and_updates_state(self) -> None:
        db = MagicMock()
        item = _fake_batch_item()
        analysis = MagicMock()
        analysis.id = "a-1"
        with patch("src.batch.service.add_spending"):
            _record_success(
                db,
                item,
                analysis,
                {"cost_usd": 0.01, "tokens": {"input": 5, "output": 3}},
                "ha",
                0.0,
            )
        assert item.analysis_id == "a-1"
        assert item.attempt_count == 1
        db.commit.assert_called_once()

    def test_record_failure_rolls_back_and_marks_error(self) -> None:
        db = MagicMock()
        item = _fake_batch_item()
        _record_failure(db, item, RuntimeError("boom"), "ha", 0.0)
        assert item.error_message == "boom"
        db.rollback.assert_called_once()
        db.commit.assert_called_once()

    def test_process_one_item_uses_dedup_path(self) -> None:
        db = MagicMock()
        item = _fake_batch_item()
        cv = MagicMock()
        cv.raw_text = "cv"
        cv.id = "cv-1"
        existing = MagicMock()
        existing.id = "a-x"
        with patch("src.batch.service.find_existing_analysis", return_value=existing):
            _process_one_item(MagicMock(), db, item, cv, None, "u")
        assert item.analysis_id == "a-x"

    def test_process_one_item_records_failure_on_exec_error(self) -> None:
        db = MagicMock()
        item = _fake_batch_item()
        cv = MagicMock()
        cv.raw_text = "cv"
        cv.id = "cv-1"
        with (
            patch("src.batch.service.find_existing_analysis", return_value=None),
            patch("src.batch.service._execute_analysis", side_effect=RuntimeError("stop")),
        ):
            _process_one_item(MagicMock(), db, item, cv, None, "u")
        assert item.error_message == "stop"


# ---------- batch/routes._serialize_batch_result ----------


class TestSerializeBatchResult:
    def test_happy_path(self) -> None:
        analysis = MagicMock()
        analysis.id = "a-1"
        analysis.role = "Dev"
        analysis.company = "Acme"
        analysis.location = "Milan"
        analysis.work_mode = "remote"
        analysis.score = 85
        analysis.recommendation = "apply"
        analysis.strengths = ["s1", "s2", "s3", "s4"]
        analysis.gaps = ["g1"]
        analysis.job_url = "u"
        analysis.model_used = "haiku"
        analysis.cost_usd = 0.1
        analysis.created_at = datetime.now(UTC)
        analysis.status = "candidato"
        analysis.benefits = None
        analysis.recruiter_info = None
        analysis.experience_required = None
        out = _serialize_batch_result(analysis, {"score_label": "ottimo"}, is_dedup=True)
        assert out["id"] == "a-1"
        assert out["is_duplicate"] is True
        assert out["strengths"] == ["s1", "s2", "s3"]
        assert out["score_label"] == "ottimo"
        assert out["benefits"] == []


# ---------- read_routes export rows ----------


class TestReadRoutesExport:
    def test_interview_export_row_shape(self) -> None:
        iv = MagicMock()
        iv.id = "iv-1"
        iv.scheduled_at = datetime.now(UTC)
        iv.outcome = "pending"
        iv.round_number = 1
        iv.interview_type = "tecnico"
        iv.platform = "zoom"
        out = _interview_export_row(iv)
        assert out["id"] == "iv-1"
        assert out["interview_type"] == "tecnico"
        assert out["scheduled_at"]

    def test_interview_export_row_handles_missing_scheduled_at(self) -> None:
        iv = MagicMock()
        iv.id = "iv-1"
        iv.scheduled_at = None
        iv.outcome = None
        iv.round_number = 1
        iv.interview_type = None
        iv.platform = None
        out = _interview_export_row(iv)
        assert out["scheduled_at"] is None

    def test_analysis_export_row_includes_interviews(self) -> None:
        a = MagicMock()
        a.id = "a-1"
        a.created_at = datetime.now(UTC)
        a.applied_at = None
        a.status = "candidato"
        a.company = "Acme"
        a.role = "Dev"
        a.location = "Milan"
        a.work_mode = "remote"
        a.salary_info = None
        a.job_url = "u"
        a.score = 80
        a.recommendation = "apply"
        a.model_used = "haiku"
        a.cost_usd = 0.1
        a.tokens_input = 10
        a.tokens_output = 5
        a.followed_up = False
        a.strengths = None
        a.gaps = None
        a.advice = None
        a.job_summary = None
        a.company_reputation = None
        a.benefits = None
        a.recruiter_info = None
        a.experience_required = None
        a.salary_data = None
        interviews = [{"id": "iv-1"}]
        out = _analysis_export_row(a, interviews)
        assert out["id"] == "a-1"
        assert out["interviews"] == interviews
        assert out["strengths"] == []
        assert out["applied_at"] is None


# ---------- document_reminder helpers ----------


class TestDocumentReminder:
    def test_group_files_by_interview(self) -> None:
        f1 = MagicMock()
        f1.interview_id = "iv-1"
        f2 = MagicMock()
        f2.interview_id = "iv-1"
        f3 = MagicMock()
        f3.interview_id = "iv-2"
        out = _group_files_by_interview([f1, f2, f3])
        assert len(out["iv-1"]) == 2
        assert len(out["iv-2"]) == 1

    def test_preload_already_notified_empty(self) -> None:
        db = MagicMock()
        assert _preload_already_notified(db, {}) == set()

    def test_preload_already_notified_extracts_ids(self) -> None:
        db = MagicMock()
        # db.query(...).filter(...).all() returns tuples
        db.query.return_value.filter.return_value.all.return_value = [
            ("document_reminder:abc",),
            ("document_reminder:def",),
            ("no_colon_here",),  # skipped
        ]
        f = MagicMock()
        f.id = "abc"
        result = _preload_already_notified(db, {"iv-1": [f]})
        assert "abc" in result
        assert "def" in result

    def test_send_reminder_email_success(self) -> None:
        with patch("src.notifications.document_reminder.resend") as mock_resend:
            ok = _send_reminder_email("subj", "<h1/>", "txt", "iv-1")
        assert ok is True
        mock_resend.Emails.send.assert_called_once()

    def test_send_reminder_email_failure_returns_false(self) -> None:
        with patch("src.notifications.document_reminder.resend") as mock_resend:
            mock_resend.Emails.send.side_effect = RuntimeError("api down")
            ok = _send_reminder_email("subj", "<h1/>", "txt", "iv-1")
        assert ok is False
