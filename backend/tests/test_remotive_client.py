"""Test per il client Remotive — completamente offline via ``httpx.MockTransport``.

Verifica:
- shape canonica WorldWild dopo normalizzazione
- response vuota → lista vuota
- parsing salary range con currency inferita
- salary non parsabile → min/max None, no raise
- HTTP 5xx → lista vuota (Sentry breadcrumb, no raise)
- timeout → lista vuota
- propagazione corretta del query param
- preservazione dell'HTML in ``description`` (rendering è del presentation layer)
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import httpx

from src.integrations import remotive


def _remotive_payload(jobs: list[dict[str, Any]]) -> str:
    """Costruisce un payload Remotive plausibile (minimal)."""
    return json.dumps(
        {
            "0-legal-notice": "Remotive jobs are protected by copyright.",
            "job-count": len(jobs),
            "jobs": jobs,
        }
    )


def _sample_job(idx: int = 1, **overrides: Any) -> dict[str, Any]:
    """Job di esempio nello shape Remotive ufficiale."""
    base = {
        "id": idx,
        "url": f"https://remotive.com/remote-jobs/{idx}",
        "title": f"Senior Python Developer #{idx}",
        "company_name": "ACME Remote Inc.",
        "company_logo": "https://example.com/logo.png",
        "category": "Software Development",
        "tags": ["python", "remote"],
        "job_type": "full_time",
        "publication_date": "2026-04-25T09:00:00",
        "candidate_required_location": "Worldwide",
        "salary": "$80,000-$120,000",
        "description": "<p>Build great <strong>Python</strong> services.</p>",
    }
    base.update(overrides)
    return base


def _make_client_with_transport(transport: httpx.MockTransport) -> Any:
    """Patch ``httpx.Client`` perché il modulo crea l'istanza internamente.

    Restituiamo un context manager builder che ``remotive.fetch_remotive_jobs``
    userà al posto del costruttore reale, così ``MockTransport`` intercetta
    le chiamate senza toccare la rete.
    """
    original_client = httpx.Client

    def _factory(*args: Any, **kwargs: Any) -> httpx.Client:
        # Forza il transport mock ignorando args runtime tipo ``timeout``
        # ma preservando il timeout per evitare regressioni di config.
        timeout = kwargs.get("timeout", 15.0)
        return original_client(transport=transport, timeout=timeout)

    return patch("src.integrations.remotive.httpx.Client", side_effect=_factory)


class TestFetchRemotiveJobs:
    def test_fetch_remotive_returns_normalized_jobs(self) -> None:
        jobs = [_sample_job(1), _sample_job(2)]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=_remotive_payload(jobs))

        with _make_client_with_transport(httpx.MockTransport(handler)):
            result = remotive.fetch_remotive_jobs(query="python")

        assert len(result) == 2
        first = result[0]
        assert first["source"] == "remotive"
        assert first["external_id"] == "1"
        assert first["title"].startswith("Senior Python Developer")
        assert first["company"] == "ACME Remote Inc."
        assert first["url"] == "https://remotive.com/remote-jobs/1"
        assert first["location"] == "Worldwide"
        assert first["category"] == "Software Development"
        assert first["contract_type"] == "full_time"
        assert first["posted_at"] is not None
        assert first["posted_at"].tzinfo is not None
        assert first["raw_payload"]["id"] == 1

    def test_fetch_remotive_handles_empty_response(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=_remotive_payload([]))

        with _make_client_with_transport(httpx.MockTransport(handler)):
            result = remotive.fetch_remotive_jobs()

        assert result == []

    def test_fetch_remotive_normalizes_salary_range(self) -> None:
        job = _sample_job(10, salary="$80,000-$120,000")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=_remotive_payload([job]))

        with _make_client_with_transport(httpx.MockTransport(handler)):
            result = remotive.fetch_remotive_jobs()

        assert len(result) == 1
        item = result[0]
        assert item["salary_min"] == 80000
        assert item["salary_max"] == 120000
        assert item["salary_currency"] == "USD"

    def test_fetch_remotive_normalizes_unparsable_salary(self) -> None:
        job = _sample_job(11, salary="competitive")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=_remotive_payload([job]))

        with _make_client_with_transport(httpx.MockTransport(handler)):
            result = remotive.fetch_remotive_jobs()

        assert len(result) == 1
        item = result[0]
        assert item["salary_min"] is None
        assert item["salary_max"] is None
        assert item["salary_currency"] == ""

    def test_fetch_remotive_handles_http_error_returns_empty(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="upstream busy")

        with _make_client_with_transport(httpx.MockTransport(handler)):
            result = remotive.fetch_remotive_jobs()

        # 5xx → graceful: lista vuota, nessun raise.
        assert result == []

    def test_fetch_remotive_handles_timeout_returns_empty(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("connect timed out", request=request)

        with _make_client_with_transport(httpx.MockTransport(handler)):
            result = remotive.fetch_remotive_jobs(timeout_s=0.1)

        assert result == []

    def test_fetch_remotive_with_query_filter(self) -> None:
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            # ``request.url.params`` espone i query string come MultiDict.
            captured["search"] = request.url.params.get("search", "")
            captured["category"] = request.url.params.get("category", "")
            captured["limit"] = request.url.params.get("limit", "")
            return httpx.Response(200, text=_remotive_payload([_sample_job(1)]))

        with _make_client_with_transport(httpx.MockTransport(handler)):
            result = remotive.fetch_remotive_jobs(query="devops", category="software-dev", limit=50)

        assert len(result) == 1
        assert captured["search"] == "devops"
        assert captured["category"] == "software-dev"
        assert captured["limit"] == "50"

    def test_fetch_remotive_handles_html_description(self) -> None:
        html_desc = "<h2>Role</h2><p>Build <em>great</em> things.</p>"
        job = _sample_job(20, description=html_desc)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=_remotive_payload([job]))

        with _make_client_with_transport(httpx.MockTransport(handler)):
            result = remotive.fetch_remotive_jobs()

        assert len(result) == 1
        # HTML preservato verbatim (Adzuna fa lo stesso): la sanitizzazione
        # è responsabilità del presentation layer, non del client.
        assert result[0]["description"] == html_desc


class TestParsing:
    def test_parse_publication_date_iso_basic(self) -> None:
        dt = remotive._parse_publication_date("2026-04-25T09:00:00")
        assert dt is not None
        assert dt.tzinfo is not None  # forzato a UTC per naive

    def test_parse_publication_date_with_z_suffix(self) -> None:
        dt = remotive._parse_publication_date("2026-04-25T09:00:00Z")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_parse_publication_date_returns_none_on_garbage(self) -> None:
        assert remotive._parse_publication_date(None) is None
        assert remotive._parse_publication_date("") is None
        assert remotive._parse_publication_date("not-a-date") is None

    def test_parse_salary_eur_with_dot_thousands(self) -> None:
        salary_min, salary_max, currency = remotive._parse_salary("80.000 – 120.000 EUR")
        assert salary_min == 80000
        assert salary_max == 120000
        assert currency == "EUR"

    def test_parse_salary_no_currency_signal(self) -> None:
        salary_min, salary_max, currency = remotive._parse_salary("80000-120000")
        assert salary_min == 80000
        assert salary_max == 120000
        assert currency == ""

    def test_parse_salary_none_or_empty(self) -> None:
        assert remotive._parse_salary(None) == (None, None, "")
        assert remotive._parse_salary("") == (None, None, "")
