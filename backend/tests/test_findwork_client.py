"""Tests for the Findwork.dev client — fully offline, no real HTTP calls.

Stubba ``httpx.Client.get`` per restituire response canned e verifica:
- graceful empty list quando ``FINDWORK_API_KEY`` manca (no HTTP call!)
- normalizzazione shape (employment_type → contract_type underscored)
- header ``Authorization: Token <key>`` correttamente inviato
- pagination cursor-based seguendo ``next``
- stop a ``max_pages`` quando ``next`` è sempre presente
- graceful empty list su HTTP error (incluso 401)
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.integrations import findwork


@pytest.fixture
def patch_settings_with_key() -> Any:
    """Inietta una API key Findwork senza toccare l'ambiente."""
    with patch.object(findwork.settings, "findwork_api_key", "test-key-123"):
        yield


@pytest.fixture
def patch_settings_no_key() -> Any:
    with patch.object(findwork.settings, "findwork_api_key", ""):
        yield


def _findwork_response(
    jobs: list[dict[str, Any]],
    *,
    next_url: str | None = None,
    status_code: int = 200,
) -> httpx.Response:
    payload = json.dumps(
        {
            "count": len(jobs),
            "next": next_url,
            "previous": None,
            "results": jobs,
        }
    )
    return httpx.Response(
        status_code,
        text=payload,
        request=httpx.Request("GET", "https://findwork.dev/api/jobs/"),
    )


def _sample_job(idx: int = 1, *, employment_type: str = "full time") -> dict[str, Any]:
    return {
        "id": idx,
        "role": f"DevOps Engineer #{idx}",
        "company_name": "ACME",
        "company_num_employees": "50-100",
        "employment_type": employment_type,
        "location": "Remote",
        "remote": True,
        "logo": "https://example.com/logo.png",
        "url": f"https://findwork.dev/jobs/{idx}",
        "text": "<p>Build cool DevOps things on Kubernetes.</p>",
        "date_posted": "2026-04-25T09:00:00Z",
        "keywords": ["devops", "kubernetes"],
        "source": "company-website",
    }


class TestFetchFindworkJobs:
    def test_fetch_findwork_returns_empty_when_no_api_key(self, patch_settings_no_key: Any) -> None:
        # No HTTP call must happen quando manca la key — pattern graceful skip.
        with patch("httpx.Client.get") as mock_get:
            result = findwork.fetch_findwork_jobs(search="devops", max_pages=1)
        assert result == []
        mock_get.assert_not_called()

    def test_fetch_findwork_basic_normalization(self, patch_settings_with_key: Any) -> None:
        with patch(
            "httpx.Client.get",
            return_value=_findwork_response([_sample_job(1), _sample_job(2)]),
        ):
            result = findwork.fetch_findwork_jobs(search="devops", max_pages=1)
        assert len(result) == 2
        item = result[0]
        assert item["source"] == "findwork"
        assert item["external_id"] == "1"
        assert item["title"] == "DevOps Engineer #1"
        assert item["company"] == "ACME"
        assert item["location"] == "Remote"
        assert item["url"] == "https://findwork.dev/jobs/1"
        assert "Kubernetes" in item["description"]
        assert item["category"] == ""
        assert item["contract_type"] == "full_time"
        assert item["salary_min"] is None
        assert item["salary_max"] is None
        assert item["salary_currency"] == ""
        assert item["posted_at"] is not None
        assert item["raw_payload"]["id"] == 1

    def test_fetch_findwork_includes_authorization_header(self, patch_settings_with_key: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_get(self: Any, url: str, **kwargs: Any) -> httpx.Response:
            captured["url"] = url
            captured["params"] = kwargs.get("params")
            captured["headers"] = kwargs.get("headers")
            return _findwork_response([_sample_job(1)])

        with patch("httpx.Client.get", new=fake_get):
            findwork.fetch_findwork_jobs(search="devops", location="Milano", max_pages=1)
        assert captured["headers"] == {"Authorization": "Token test-key-123"}
        # Param iniziali devono includere search/location/remote.
        assert captured["params"] is not None
        assert captured["params"]["search"] == "devops"
        assert captured["params"]["location"] == "Milano"
        assert captured["params"]["remote"] == "true"

    def test_fetch_findwork_paginates_via_next_url(self, patch_settings_with_key: Any) -> None:
        page1 = _findwork_response(
            [_sample_job(1)],
            next_url="https://findwork.dev/api/jobs/?page=2",
        )
        page2 = _findwork_response([_sample_job(2)], next_url=None)

        captured_urls: list[str] = []

        def fake_get(self: Any, url: str, **kwargs: Any) -> httpx.Response:
            captured_urls.append(url)
            return page1 if len(captured_urls) == 1 else page2

        with patch("httpx.Client.get", new=fake_get):
            result = findwork.fetch_findwork_jobs(search="devops", max_pages=5)
        assert len(result) == 2
        assert {r["external_id"] for r in result} == {"1", "2"}
        # Seconda chiamata DEVE usare l'URL completo del cursore ``next``.
        assert captured_urls[0] == "https://findwork.dev/api/jobs/"
        assert captured_urls[1] == "https://findwork.dev/api/jobs/?page=2"

    def test_fetch_findwork_stops_at_max_pages(self, patch_settings_with_key: Any) -> None:
        # ``next`` sempre presente: senza guard usciremmo in loop, ma max_pages=2
        # deve fermare dopo 2 fetch.
        always_next = _findwork_response(
            [_sample_job(1)],
            next_url="https://findwork.dev/api/jobs/?page=99",
        )
        mock_get = MagicMock(return_value=always_next)
        with patch("httpx.Client.get", new=mock_get):
            result = findwork.fetch_findwork_jobs(search="devops", max_pages=2)
        assert mock_get.call_count == 2
        # Stesso external_id su entrambe le pagine → dedup intra-run a 1 record.
        assert len(result) == 1

    def test_fetch_findwork_normalizes_employment_type(self, patch_settings_with_key: Any) -> None:
        cases = [
            ("full time", "full_time"),
            ("PART TIME", "part_time"),
            ("contract", "contract"),
            ("", ""),
        ]
        for raw_value, expected in cases:
            job = _sample_job(1, employment_type=raw_value)
            with patch("httpx.Client.get", return_value=_findwork_response([job])):
                result = findwork.fetch_findwork_jobs(search="devops", max_pages=1)
            assert result[0]["contract_type"] == expected, f"input={raw_value!r}"

    def test_fetch_findwork_handles_http_error_returns_empty(self, patch_settings_with_key: Any) -> None:
        error_resp = httpx.Response(
            503,
            text="upstream busy",
            request=httpx.Request("GET", "https://findwork.dev/api/jobs/"),
        )
        with patch("httpx.Client.get", return_value=error_resp):
            result = findwork.fetch_findwork_jobs(search="devops", max_pages=2)
        assert result == []

    def test_fetch_findwork_handles_401_returns_empty(self, patch_settings_with_key: Any) -> None:
        # Auth fail (key revocata o sbagliata) → no raise, lista vuota.
        unauthorized = httpx.Response(
            401,
            text='{"detail":"Invalid token."}',
            request=httpx.Request("GET", "https://findwork.dev/api/jobs/"),
        )
        with patch("httpx.Client.get", return_value=unauthorized):
            result = findwork.fetch_findwork_jobs(search="devops", max_pages=1)
        assert result == []


class TestParsing:
    # Test sui parser ISO datetime sono ora centralizzati in
    # ``test_integrations_common.py::test_parse_iso_datetime_*`` dopo
    # l'estrazione dell'helper in ``integrations._common``.
    def test_normalize_drops_rows_missing_id_or_role(self) -> None:
        assert findwork._normalize({"id": "", "role": "x"}) is None
        assert findwork._normalize({"id": 5, "role": ""}) is None
        ok = findwork._normalize(_sample_job(7))
        assert ok is not None
        assert ok["external_id"] == "7"
