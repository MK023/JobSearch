"""Tests for the Adzuna client — fully offline, no real HTTP calls.

Stubs ``httpx.Client.get`` to return canned responses so we can verify:
- normalization shape
- pagination + early stop on short page
- intra-run dedup by external_id
- graceful empty list when keys are missing
- graceful empty list on HTTP error (no raise)
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from src.integrations import adzuna


@pytest.fixture
def patch_settings_with_keys() -> Any:
    """Inject Adzuna keys into settings without touching the env."""
    with (
        patch.object(adzuna.settings, "adzuna_app_id", "test-id"),
        patch.object(adzuna.settings, "adzuna_app_key", "test-key"),
    ):
        yield


@pytest.fixture
def patch_settings_no_keys() -> Any:
    with patch.object(adzuna.settings, "adzuna_app_id", ""), patch.object(adzuna.settings, "adzuna_app_key", ""):
        yield


def _adzuna_response(jobs: list[dict[str, Any]], status_code: int = 200) -> httpx.Response:
    payload = json.dumps({"results": jobs, "count": len(jobs)})
    # raise_for_status() needs a request bound on the Response or it explodes
    # with a ResponseNotRead-style RuntimeError. Bind a fake one.
    return httpx.Response(
        status_code,
        text=payload,
        request=httpx.Request("GET", "https://api.adzuna.com/test"),
    )


def _sample_job(idx: int = 1) -> dict[str, Any]:
    return {
        "id": f"job-{idx}",
        "title": f"Senior DevOps Engineer #{idx}",
        "company": {"display_name": "TestCorp"},
        "location": {"display_name": "Milano, Provincia di Milano"},
        "redirect_url": f"https://example.com/job/{idx}",
        "description": "Full remote, Kubernetes + AWS.",
        "salary_min": 50000,
        "salary_max": 70000,
        "contract_type": "permanent",
        "contract_time": "full_time",
        "category": {"label": "IT Jobs"},
        "created": "2026-04-25T09:00:00Z",
    }


class TestFetchAdzunaJobs:
    def test_returns_empty_when_keys_missing(self, patch_settings_no_keys: Any) -> None:
        result = adzuna.fetch_adzuna_jobs(what="devops", max_pages=1)
        assert result == []

    def test_normalizes_single_page(self, patch_settings_with_keys: Any) -> None:
        with patch("httpx.Client.get", return_value=_adzuna_response([_sample_job(1)])):
            result = adzuna.fetch_adzuna_jobs(what="devops", max_pages=1, results_per_page=50)
        assert len(result) == 1
        item = result[0]
        assert item["source"] == "adzuna"
        assert item["external_id"] == "job-1"
        assert item["title"].startswith("Senior DevOps Engineer")
        assert item["company"] == "TestCorp"
        assert item["location"] == "Milano, Provincia di Milano"
        assert item["url"] == "https://example.com/job/1"
        assert item["salary_min"] == 50000
        assert item["salary_max"] == 70000
        assert item["contract_type"] == "permanent"
        assert item["category"] == "IT Jobs"
        assert item["posted_at"] is not None
        assert item["raw_payload"]["id"] == "job-1"

    def test_dedup_within_run_by_external_id(self, patch_settings_with_keys: Any) -> None:
        # Same job appearing on two pages must collapse.
        same_job = _sample_job(42)
        responses = [_adzuna_response([same_job, _sample_job(43)]), _adzuna_response([same_job])]
        with patch("httpx.Client.get", side_effect=responses):
            result = adzuna.fetch_adzuna_jobs(what="devops", max_pages=2, results_per_page=2)
        assert len(result) == 2
        assert {r["external_id"] for r in result} == {"job-42", "job-43"}

    def test_pagination_stops_on_short_page(self, patch_settings_with_keys: Any) -> None:
        # If results_per_page=10 and the first page returns 5, we should NOT
        # fetch page 2 (Adzuna semantics: short page = end of results).
        responses = [_adzuna_response([_sample_job(i) for i in range(5)])]
        with patch("httpx.Client.get", side_effect=responses) as mock_get:
            result = adzuna.fetch_adzuna_jobs(what="devops", max_pages=4, results_per_page=10)
        assert mock_get.call_count == 1
        assert len(result) == 5

    def test_drops_rows_missing_id_or_title(self, patch_settings_with_keys: Any) -> None:
        bad = {"id": "", "title": "Has no id"}
        bad2 = {"id": "x", "title": ""}
        good = _sample_job(99)
        with patch("httpx.Client.get", return_value=_adzuna_response([bad, bad2, good])):
            result = adzuna.fetch_adzuna_jobs(what="devops", max_pages=1, results_per_page=50)
        assert len(result) == 1
        assert result[0]["external_id"] == "job-99"

    def test_swallows_http_error_returns_partial(self, patch_settings_with_keys: Any) -> None:
        # First page OK, second page errors → keep what we got, don't raise.
        responses = [
            _adzuna_response([_sample_job(1)]),
            httpx.Response(
                503,
                text="upstream busy",
                request=httpx.Request("GET", "https://api.adzuna.com/test"),
            ),
        ]
        with patch("httpx.Client.get", side_effect=responses):
            result = adzuna.fetch_adzuna_jobs(what="devops", max_pages=2, results_per_page=1)
        # First page yielded 1, second page errored → still 1 returned.
        assert len(result) == 1


class TestParsing:
    def test_parse_created_iso_with_z_suffix(self) -> None:
        dt = adzuna._parse_created("2026-04-25T09:00:00Z")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_parse_created_returns_none_on_garbage(self) -> None:
        assert adzuna._parse_created(None) is None
        assert adzuna._parse_created("") is None
        assert adzuna._parse_created("not-a-date") is None

    def test_safe_int_handles_none_and_strings(self) -> None:
        assert adzuna._safe_int(None) is None
        assert adzuna._safe_int(42) == 42
        assert adzuna._safe_int("42") == 42
        assert adzuna._safe_int("not-a-number") is None
