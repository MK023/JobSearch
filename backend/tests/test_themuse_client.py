"""Test per il client The Muse — fully offline via ``httpx.MockTransport``.

Verifichiamo:
- normalizzazione single page
- pagination multi-page (page_count > 1)
- stop a max_pages quando page_count e' alto
- locations array → string CSV
- company nested dict → string flat
- contract_type ``"Full-Time"`` → ``"full_time"``
- date ISO con suffix ``Z`` → datetime tz-aware
- api_key in query params quando passato
- HTTP error → lista vuota (graceful)
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import httpx

from src.integrations import themuse


def _muse_response(
    jobs: list[dict[str, Any]],
    *,
    page: int = 1,
    page_count: int = 1,
    status_code: int = 200,
) -> httpx.Response:
    payload = json.dumps(
        {
            "results": jobs,
            "page": page,
            "page_count": page_count,
            "items_per_page": 20,
            "total": len(jobs),
        }
    )
    return httpx.Response(
        status_code,
        text=payload,
        request=httpx.Request("GET", "https://www.themuse.com/api/public/jobs"),
    )


def _sample_job(idx: int = 1) -> dict[str, Any]:
    return {
        "id": 1000 + idx,
        "name": f"Senior DevOps Engineer #{idx}",
        "company": {"id": 456, "name": "ACME"},
        "locations": [{"name": "Remote"}, {"name": "Berlin, Germany"}],
        "levels": [{"name": "Senior Level"}],
        "categories": [{"name": "Engineering"}],
        "contents": "<html><p>Build cool stuff.</p></html>",
        "type": "Full-Time",
        "publication_date": "2024-06-01T10:30:00.000Z",
        "refs": {"landing_page": f"https://www.themuse.com/jobs/job-{idx}"},
    }


def test_fetch_themuse_basic_normalization() -> None:
    """1 page con 2 jobs → 2 risultati normalizzati con campi attesi."""
    jobs = [_sample_job(1), _sample_job(2)]
    with patch("httpx.Client.get", return_value=_muse_response(jobs, page=1, page_count=1)):
        result = themuse.fetch_themuse_jobs(category="Engineering", max_pages=1)

    assert len(result) == 2
    item = result[0]
    assert item["source"] == "themuse"
    assert item["external_id"] == "1001"
    assert item["title"].startswith("Senior DevOps Engineer")
    assert item["company"] == "ACME"
    assert item["url"] == "https://www.themuse.com/jobs/job-1"
    assert item["description"].startswith("<html>")
    assert item["category"] == "Engineering"
    assert item["salary_min"] is None
    assert item["salary_max"] is None
    assert item["salary_currency"] == ""
    assert item["raw_payload"]["id"] == 1001


def test_fetch_themuse_paginates_multiple_pages() -> None:
    """``page_count=3`` → fetch tutte e tre le pagine."""
    responses = [
        _muse_response([_sample_job(1)], page=1, page_count=3),
        _muse_response([_sample_job(2)], page=2, page_count=3),
        _muse_response([_sample_job(3)], page=3, page_count=3),
    ]
    with patch("httpx.Client.get", side_effect=responses) as mock_get:
        result = themuse.fetch_themuse_jobs(max_pages=10)

    assert mock_get.call_count == 3
    assert len(result) == 3
    assert {r["external_id"] for r in result} == {"1001", "1002", "1003"}


def test_fetch_themuse_stops_at_max_pages() -> None:
    """``page_count=10`` ma ``max_pages=2`` → solo 2 fetch."""
    responses = [
        _muse_response([_sample_job(1)], page=1, page_count=10),
        _muse_response([_sample_job(2)], page=2, page_count=10),
        # Una terza non dovrebbe mai essere consumata.
        _muse_response([_sample_job(3)], page=3, page_count=10),
    ]
    with patch("httpx.Client.get", side_effect=responses) as mock_get:
        result = themuse.fetch_themuse_jobs(max_pages=2)

    assert mock_get.call_count == 2
    assert len(result) == 2


def test_fetch_themuse_normalizes_locations_array_to_string() -> None:
    """Array locations → CSV string ordinata come fornita."""
    job = _sample_job(1)
    job["locations"] = [
        {"name": "Remote"},
        {"name": "Berlin, Germany"},
        {"name": "Milano"},
    ]
    with patch("httpx.Client.get", return_value=_muse_response([job])):
        result = themuse.fetch_themuse_jobs(max_pages=1)

    assert result[0]["location"] == "Remote, Berlin, Germany, Milano"


def test_fetch_themuse_normalizes_company_nested_dict() -> None:
    """``company.name`` nested → flat string sul campo ``company``."""
    job = _sample_job(1)
    job["company"] = {"id": 999, "name": "BigCorp Inc."}
    with patch("httpx.Client.get", return_value=_muse_response([job])):
        result = themuse.fetch_themuse_jobs(max_pages=1)

    assert result[0]["company"] == "BigCorp Inc."


def test_fetch_themuse_normalizes_contract_type_full_time() -> None:
    """``"Full-Time"`` → ``"full_time"`` (lower + dash→underscore)."""
    job = _sample_job(1)
    job["type"] = "Full-Time"
    with patch("httpx.Client.get", return_value=_muse_response([job])):
        result = themuse.fetch_themuse_jobs(max_pages=1)

    assert result[0]["contract_type"] == "full_time"


def test_fetch_themuse_normalizes_iso_z_date() -> None:
    """ISO date con suffix ``Z`` → datetime tz-aware UTC."""
    job = _sample_job(1)
    job["publication_date"] = "2024-06-01T10:30:00.000Z"
    with patch("httpx.Client.get", return_value=_muse_response([job])):
        result = themuse.fetch_themuse_jobs(max_pages=1)

    posted = result[0]["posted_at"]
    assert posted is not None
    assert posted.tzinfo is not None
    assert posted.year == 2024
    assert posted.month == 6
    assert posted.day == 1


def test_fetch_themuse_includes_api_key_when_provided() -> None:
    """Quando ``api_key`` e' passato, deve finire nei query params."""
    captured: dict[str, Any] = {}

    def fake_get(self: httpx.Client, url: str, **kwargs: Any) -> httpx.Response:
        captured["url"] = url
        captured["params"] = kwargs.get("params", {})
        return _muse_response([_sample_job(1)])

    with patch("httpx.Client.get", new=fake_get):
        themuse.fetch_themuse_jobs(api_key="secret-key-123", max_pages=1)

    assert captured["params"].get("api_key") == "secret-key-123"


def test_fetch_themuse_handles_http_error_returns_empty() -> None:
    """503 alla prima pagina → lista vuota, niente raise."""
    error_resp = httpx.Response(
        503,
        text="upstream busy",
        request=httpx.Request("GET", "https://www.themuse.com/api/public/jobs"),
    )
    with patch("httpx.Client.get", return_value=error_resp):
        result = themuse.fetch_themuse_jobs(max_pages=3)

    assert result == []
