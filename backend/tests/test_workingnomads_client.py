"""Test del client Working Nomads — completamente offline, no HTTP reali.

Stub di ``httpx.Client.get`` con risposte canned per verificare:
- normalizzazione (shape)
- gestione array vuoto
- url usato come external_id
- fallback location -> country quando location e' vuoto
- filtro client-side per category (substring case-insensitive)
- parsing data ISO con suffisso Z
- graceful empty list su errore HTTP (no raise)
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import httpx

from src.integrations import workingnomads


def _wn_response(items: list[dict[str, Any]], status_code: int = 200) -> httpx.Response:
    """Working Nomads ritorna un array JSON top-level (NO wrapper object)."""
    return httpx.Response(
        status_code,
        text=json.dumps(items),
        request=httpx.Request("GET", workingnomads.WORKINGNOMADS_ENDPOINT),
    )


def _sample_job(idx: int = 1, *, category: str = "DevOps & SysAdmin", location: str = "Remote") -> dict[str, Any]:
    return {
        "url": f"https://www.workingnomads.com/jobs/{idx}",
        "title": f"Senior DevOps Engineer #{idx}",
        "company_name": "ACME Inc",
        "category_name": category,
        "tags": "aws,kubernetes,docker",
        "description": "<html>Full remote, K8s + AWS.</html>",
        "country": "Worldwide",
        "region": "",
        "location": location,
        "pub_date": "2024-06-01T10:30:00Z",
        "company_logo_url": "https://cdn.example.com/logo.png",
    }


class TestFetchWorkingNomadsJobs:
    def test_fetch_workingnomads_basic_normalization(self) -> None:
        jobs = [_sample_job(1), _sample_job(2)]
        with patch("httpx.Client.get", return_value=_wn_response(jobs)):
            result = workingnomads.fetch_workingnomads_jobs()
        assert len(result) == 2
        first = result[0]
        assert first["source"] == "workingnomads"
        assert first["external_id"] == "https://www.workingnomads.com/jobs/1"
        assert first["title"].startswith("Senior DevOps Engineer")
        assert first["company"] == "ACME Inc"
        assert first["url"] == "https://www.workingnomads.com/jobs/1"
        assert first["location"] == "Remote"
        assert first["category"] == "DevOps & SysAdmin"
        assert first["contract_type"] == ""
        assert first["salary_min"] is None
        assert first["salary_max"] is None
        assert first["salary_currency"] == ""
        assert first["posted_at"] is not None
        assert first["raw_payload"]["tags"] == "aws,kubernetes,docker"

    def test_fetch_workingnomads_handles_empty_array(self) -> None:
        with patch("httpx.Client.get", return_value=_wn_response([])):
            result = workingnomads.fetch_workingnomads_jobs()
        assert result == []

    def test_fetch_workingnomads_uses_url_as_external_id(self) -> None:
        # Working Nomads non espone ``id``: l'url e' la chiave stabile cross-poll.
        job = _sample_job(123)
        with patch("httpx.Client.get", return_value=_wn_response([job])):
            result = workingnomads.fetch_workingnomads_jobs()
        assert len(result) == 1
        assert result[0]["external_id"] == job["url"]
        assert result[0]["external_id"] == result[0]["url"]

    def test_fetch_workingnomads_falls_back_to_country_when_location_empty(self) -> None:
        job = _sample_job(1, location="")
        # country = "Worldwide" deve essere usato come fallback.
        with patch("httpx.Client.get", return_value=_wn_response([job])):
            result = workingnomads.fetch_workingnomads_jobs()
        assert len(result) == 1
        assert result[0]["location"] == "Worldwide"

    def test_fetch_workingnomads_filters_by_category_substring(self) -> None:
        jobs = [
            _sample_job(1, category="DevOps & SysAdmin"),
            _sample_job(2, category="Marketing"),
            _sample_job(3, category="Software Development"),
            _sample_job(4, category="devops/cloud"),  # case-insensitive match
        ]
        with patch("httpx.Client.get", return_value=_wn_response(jobs)):
            result = workingnomads.fetch_workingnomads_jobs(category_filter="DevOps")
        ids = {r["external_id"] for r in result}
        assert ids == {
            "https://www.workingnomads.com/jobs/1",
            "https://www.workingnomads.com/jobs/4",
        }

    def test_fetch_workingnomads_no_filter_keeps_all(self) -> None:
        jobs = [
            _sample_job(1, category="DevOps & SysAdmin"),
            _sample_job(2, category="Marketing"),
            _sample_job(3, category="Software Development"),
        ]
        with patch("httpx.Client.get", return_value=_wn_response(jobs)):
            result = workingnomads.fetch_workingnomads_jobs(category_filter="")
        assert len(result) == 3

    def test_fetch_workingnomads_normalizes_iso_z_date(self) -> None:
        job = _sample_job(1)
        job["pub_date"] = "2024-06-01T10:30:00Z"
        with patch("httpx.Client.get", return_value=_wn_response([job])):
            result = workingnomads.fetch_workingnomads_jobs()
        posted = result[0]["posted_at"]
        assert posted is not None
        assert posted.tzinfo is not None
        assert posted.year == 2024
        assert posted.month == 6
        assert posted.day == 1

    def test_fetch_workingnomads_handles_http_error_returns_empty(self) -> None:
        # 503 upstream: il client deve loggare ma non sollevare.
        bad_response = httpx.Response(
            503,
            text="upstream busy",
            request=httpx.Request("GET", workingnomads.WORKINGNOMADS_ENDPOINT),
        )
        with patch("httpx.Client.get", return_value=bad_response):
            result = workingnomads.fetch_workingnomads_jobs()
        assert result == []
