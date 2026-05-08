"""Test del client Jobicy — completamente offline, niente HTTP reali.

Usa ``httpx.MockTransport`` per intercettare la GET verso ``jobicy.com`` e
restituire risposte canoniche, così possiamo verificare:
- shape della normalizzazione
- conversione salari da stringa a int
- estrazione primo elemento da liste (industry / jobType)
- pubDate naive → UTC
- propagazione filtri in query string
- empty list graceful su errori HTTP
"""

from __future__ import annotations

import json
from datetime import UTC
from typing import Any
from unittest.mock import patch

import httpx

from src.integrations import jobicy


def _jobicy_response(jobs: list[dict[str, Any]], status_code: int = 200) -> httpx.Response:
    payload = json.dumps({"apiVersion": "2", "jobCount": len(jobs), "jobs": jobs})
    return httpx.Response(
        status_code,
        text=payload,
        request=httpx.Request("GET", "https://jobicy.com/api/v2/remote-jobs"),
    )


def _sample_job(idx: int = 1, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": idx,
        "url": f"https://jobicy.com/jobs/{idx}-senior-devops",
        "jobSlug": f"{idx}-senior-devops",
        "jobTitle": f"Senior DevOps Engineer #{idx}",
        "companyName": "RemoteCorp",
        "companyLogo": "https://cdn.example.com/logo.png",
        "jobIndustry": ["DevOps & Sysadmin"],
        "jobType": ["full-time"],
        "jobGeo": "USA, EMEA",
        "jobLevel": "Senior",
        "jobExcerpt": "Brief excerpt",
        "jobDescription": "<p>Full remote, Kubernetes + AWS.</p>",
        "pubDate": "2024-06-01 10:30:00",
        "annualSalaryMin": "80000",
        "annualSalaryMax": "120000",
        "salaryCurrency": "USD",
    }
    base.update(overrides)
    return base


class TestFetchJobicyJobs:
    def test_fetch_jobicy_basic_normalization(self) -> None:
        jobs = [_sample_job(1), _sample_job(2)]
        with patch("httpx.Client.get", return_value=_jobicy_response(jobs)):
            result = jobicy.fetch_jobicy_jobs(count=50)
        assert len(result) == 2
        item = result[0]
        assert item["source"] == "jobicy"
        assert item["external_id"] == "1"
        assert item["title"].startswith("Senior DevOps Engineer")
        assert item["company"] == "RemoteCorp"
        assert item["url"] == "https://jobicy.com/jobs/1-senior-devops"
        assert item["description"] == "<p>Full remote, Kubernetes + AWS.</p>"
        assert item["location"] == "USA, EMEA"
        assert item["salary_currency"] == "USD"
        assert item["contract_type"] == "full_time"
        assert item["raw_payload"]["id"] == 1

    def test_fetch_jobicy_handles_empty_jobs(self) -> None:
        with patch("httpx.Client.get", return_value=_jobicy_response([])):
            result = jobicy.fetch_jobicy_jobs(count=50)
        assert result == []

    def test_fetch_jobicy_normalizes_string_salary_to_int(self) -> None:
        # Jobicy serializza i salari come stringa: "80000" deve diventare 80000.
        with patch("httpx.Client.get", return_value=_jobicy_response([_sample_job(1)])):
            result = jobicy.fetch_jobicy_jobs(count=10)
        assert result[0]["salary_min"] == 80000
        assert result[0]["salary_max"] == 120000
        assert isinstance(result[0]["salary_min"], int)

    def test_fetch_jobicy_normalizes_missing_salary(self) -> None:
        job = _sample_job(1, annualSalaryMin=None, annualSalaryMax=None)
        with patch("httpx.Client.get", return_value=_jobicy_response([job])):
            result = jobicy.fetch_jobicy_jobs(count=10)
        assert result[0]["salary_min"] is None
        assert result[0]["salary_max"] is None

    def test_fetch_jobicy_normalizes_industry_list_to_first_element(self) -> None:
        job = _sample_job(1, jobIndustry=["DevOps", "Cloud"])
        with patch("httpx.Client.get", return_value=_jobicy_response([job])):
            result = jobicy.fetch_jobicy_jobs(count=10)
        assert result[0]["category"] == "DevOps"

    def test_fetch_jobicy_normalizes_pubdate_to_utc_datetime(self) -> None:
        with patch("httpx.Client.get", return_value=_jobicy_response([_sample_job(1)])):
            result = jobicy.fetch_jobicy_jobs(count=10)
        posted_at = result[0]["posted_at"]
        assert posted_at is not None
        assert posted_at.tzinfo is not None
        assert posted_at.utcoffset() == UTC.utcoffset(posted_at)
        assert posted_at.year == 2024
        assert posted_at.month == 6
        assert posted_at.hour == 10

    def test_fetch_jobicy_handles_http_error_returns_empty(self) -> None:
        error_resp = httpx.Response(
            503,
            text="upstream busy",
            request=httpx.Request("GET", "https://jobicy.com/api/v2/remote-jobs"),
        )
        with patch("httpx.Client.get", return_value=error_resp):
            result = jobicy.fetch_jobicy_jobs(count=10)
        assert result == []

    def test_fetch_jobicy_passes_filters_in_query_params(self) -> None:
        with patch("httpx.Client.get", return_value=_jobicy_response([])) as mock_get:
            jobicy.fetch_jobicy_jobs(count=25, geo="europe", industry="dev", tag="python")
        assert mock_get.call_count == 1
        _args, kwargs = mock_get.call_args
        params = kwargs["params"]
        assert params["count"] == 25
        assert params["geo"] == "europe"
        assert params["industry"] == "dev"
        assert params["tag"] == "python"

    def test_fetch_jobicy_omits_empty_filters(self) -> None:
        # Filtri vuoti non devono finire nella query string (lato server li
        # tratterebbe come "filtra per stringa vuota").
        with patch("httpx.Client.get", return_value=_jobicy_response([])) as mock_get:
            jobicy.fetch_jobicy_jobs(count=10)
        _args, kwargs = mock_get.call_args
        params = kwargs["params"]
        assert "geo" not in params
        assert "industry" not in params
        assert "tag" not in params

    def test_fetch_jobicy_drops_rows_missing_id_or_title(self) -> None:
        bad_no_id = _sample_job(1, id=None)
        bad_no_title = _sample_job(2, jobTitle="")
        good = _sample_job(99)
        with patch(
            "httpx.Client.get",
            return_value=_jobicy_response([bad_no_id, bad_no_title, good]),
        ):
            result = jobicy.fetch_jobicy_jobs(count=50)
        assert len(result) == 1
        assert result[0]["external_id"] == "99"

    def test_fetch_jobicy_default_invocation_never_raises(self) -> None:
        # Guard contro 502 in produzione su /api/v1/worldwild/ingest/jobicy.
        # ``run_jobicy_ingest`` chiama ``fetch_jobicy_jobs(industry="", geo="",
        # tag="", count=50)``: una qualsiasi ``Exception`` non gestita qui
        # propaga in ``_execute_ingest`` → route handler → ``HTTPException 502``.
        # Verifica che gli errori comuni (timeout, 5xx, JSON malformato,
        # payload non-dict, payload con ``jobs`` non lista) restino assorbiti
        # dal contract "ritorna lista vuota su errore".
        scenarios: list[Any] = [
            httpx.Response(
                500,
                text="upstream",
                request=httpx.Request("GET", jobicy.JOBICY_BASE),
            ),
            httpx.Response(
                200,
                text="<html>not json</html>",
                request=httpx.Request("GET", jobicy.JOBICY_BASE),
            ),
            httpx.Response(
                200,
                text=json.dumps([1, 2, 3]),  # payload top-level list, non dict
                request=httpx.Request("GET", jobicy.JOBICY_BASE),
            ),
            httpx.Response(
                200,
                text=json.dumps({"jobs": "not-a-list"}),  # ``jobs`` shape rotta
                request=httpx.Request("GET", jobicy.JOBICY_BASE),
            ),
        ]
        for resp in scenarios:
            with patch("httpx.Client.get", return_value=resp):
                result = jobicy.fetch_jobicy_jobs()  # tutti i default
            assert isinstance(result, list)
            assert result == []

        # Network error path (httpx.HTTPError sottoclassi).
        with patch("httpx.Client.get", side_effect=httpx.ConnectError("dns")):
            result = jobicy.fetch_jobicy_jobs()
        assert result == []


class TestParsing:
    # Test sui parser ISO datetime sono ora centralizzati in
    # ``test_integrations_common.py::test_parse_iso_datetime_*`` dopo
    # l'estrazione dell'helper in ``integrations._common`` (incluso il
    # caso space-separator naive ``"YYYY-MM-DD HH:MM:SS"`` di Jobicy).
    def test_safe_int_handles_string_int_and_none(self) -> None:
        assert jobicy._safe_int(None) is None
        assert jobicy._safe_int("") is None
        assert jobicy._safe_int(42) == 42
        assert jobicy._safe_int("42") == 42
        assert jobicy._safe_int("not-a-number") is None

    def test_first_of_list_handles_empty_and_non_list(self) -> None:
        assert jobicy._first_of_list([], max_len=32) == ""
        assert jobicy._first_of_list(None, max_len=32) == ""
        assert jobicy._first_of_list("not-a-list", max_len=32) == ""
        assert jobicy._first_of_list(["DevOps"], max_len=32) == "DevOps"

    def test_normalize_contract_type_dasherized_to_underscore(self) -> None:
        assert jobicy._normalize_contract_type(["full-time"]) == "full_time"
        assert jobicy._normalize_contract_type(["Part-Time"]) == "part_time"
        assert jobicy._normalize_contract_type([]) == ""
        assert jobicy._normalize_contract_type(None) == ""
