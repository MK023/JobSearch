"""Test del client Remote OK — completamente offline, nessuna chiamata HTTP reale.

Si usa ``httpx.MockTransport`` per intercettare le richieste e tornare risposte
canned, così verifichiamo:
- skip del disclaimer legale (primo item con chiave ``"legal"``)
- normalizzazione campi base + date ISO + salari + currency USD
- presenza User-Agent custom (Remote OK blocca il default ``python-httpx``)
- query string ``tags=devops,python`` quando passiamo tuple
- degradazione graceful su 403/errori → ``[]``
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from unittest.mock import patch

import httpx

from src.integrations import remoteok


def _legal_notice() -> dict[str, Any]:
    return {"legal": "See https://remoteok.com/terms"}


def _sample_job(idx: int = 1, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": f"remoteok-{idx}",
        "slug": f"company-role-{idx}",
        "epoch": 1717689600,
        "date": "2024-06-01T10:30:00+00:00",
        "company": "TestCorp",
        "company_logo": "https://example.com/logo.png",
        "position": f"Senior DevOps Engineer #{idx}",
        "tags": ["devops", "aws"],
        "logo": "https://example.com/logo.png",
        "description": "<p>Full remote, Kubernetes + AWS.</p>",
        "location": "Worldwide",
        "salary_min": 80000,
        "salary_max": 120000,
        "apply_url": f"https://remoteok.com/apply/{idx}",
        "url": f"https://remoteok.com/remote-jobs/{idx}",
    }
    base.update(overrides)
    return base


def _build_response(payload: list[dict[str, Any]], status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        text=json.dumps(payload),
        request=httpx.Request("GET", remoteok.REMOTEOK_BASE),
    )


def test_fetch_remoteok_basic_normalization() -> None:
    payload = [_legal_notice(), _sample_job(1), _sample_job(2)]
    with patch("httpx.Client.get", return_value=_build_response(payload)):
        result = remoteok.fetch_remoteok_jobs()

    assert len(result) == 2
    first = result[0]
    assert first["source"] == "remoteok"
    assert first["external_id"] == "remoteok-1"
    assert first["title"].startswith("Senior DevOps Engineer")
    assert first["company"] == "TestCorp"
    assert first["location"] == "Worldwide"
    assert first["url"] == "https://remoteok.com/remote-jobs/1"
    assert first["category"] == ""
    assert first["contract_type"] == ""
    assert first["raw_payload"]["id"] == "remoteok-1"


def test_fetch_remoteok_handles_empty_response() -> None:
    # Solo il disclaimer legale → nessun job utile.
    with patch("httpx.Client.get", return_value=_build_response([_legal_notice()])):
        result = remoteok.fetch_remoteok_jobs()
    assert result == []


def test_fetch_remoteok_includes_user_agent_header() -> None:
    captured: dict[str, Any] = {}

    real_get = httpx.Client.get

    def spy_get(self: httpx.Client, *args: Any, **kwargs: Any) -> httpx.Response:
        # Catturiamo lo User-Agent effettivamente in uscita dal client.
        captured["user_agent"] = self.headers.get("user-agent")
        return _build_response([_legal_notice(), _sample_job(1)])

    with patch.object(httpx.Client, "get", spy_get):
        result = remoteok.fetch_remoteok_jobs()

    # Cleanup, evita il warning di unused.
    assert real_get is not None
    assert captured["user_agent"] == remoteok.USER_AGENT
    assert remoteok.USER_AGENT.startswith("Worldwild/")
    assert len(result) == 1


def test_fetch_remoteok_normalizes_iso_date_to_datetime() -> None:
    payload = [_legal_notice(), _sample_job(1, date="2024-06-01T10:30:00+00:00")]
    with patch("httpx.Client.get", return_value=_build_response(payload)):
        result = remoteok.fetch_remoteok_jobs()

    assert len(result) == 1
    posted_at = result[0]["posted_at"]
    assert isinstance(posted_at, datetime)
    assert posted_at.tzinfo is not None
    assert posted_at.year == 2024
    assert posted_at.month == 6
    assert posted_at.day == 1


def test_fetch_remoteok_normalizes_salary_with_usd_currency() -> None:
    payload = [_legal_notice(), _sample_job(1, salary_min=80000, salary_max=120000)]
    with patch("httpx.Client.get", return_value=_build_response(payload)):
        result = remoteok.fetch_remoteok_jobs()

    assert len(result) == 1
    item = result[0]
    assert item["salary_min"] == 80000
    assert item["salary_max"] == 120000
    assert item["salary_currency"] == "USD"


def test_fetch_remoteok_normalizes_missing_salary() -> None:
    job = _sample_job(1)
    job.pop("salary_min")
    job.pop("salary_max")
    with patch("httpx.Client.get", return_value=_build_response([_legal_notice(), job])):
        result = remoteok.fetch_remoteok_jobs()

    assert len(result) == 1
    item = result[0]
    assert item["salary_min"] is None
    assert item["salary_max"] is None
    assert item["salary_currency"] == ""


def test_fetch_remoteok_handles_http_error_returns_empty() -> None:
    # Remote OK risponde 403 quando manca lo User-Agent o è blacklistato.
    error_response = httpx.Response(
        403,
        text="Forbidden",
        request=httpx.Request("GET", remoteok.REMOTEOK_BASE),
    )
    with patch("httpx.Client.get", return_value=error_response):
        result = remoteok.fetch_remoteok_jobs()
    assert result == []


def test_fetch_remoteok_passes_tags_filter() -> None:
    captured: dict[str, Any] = {}

    def spy_get(self: httpx.Client, url: str, *args: Any, **kwargs: Any) -> httpx.Response:
        params = kwargs.get("params") or {}
        captured["tags_param"] = params.get("tags")
        return _build_response([_legal_notice(), _sample_job(1)])

    with patch.object(httpx.Client, "get", spy_get):
        result = remoteok.fetch_remoteok_jobs(tags=("devops", "python"))

    assert captured["tags_param"] == "devops,python"
    assert len(result) == 1


def test_fetch_remoteok_skips_legal_notice_first_item() -> None:
    # Caso esplicito: il disclaimer non deve mai diventare un job normalizzato,
    # neanche con campi accidentalmente compatibili.
    legal_with_noise = {"legal": "Terms apply", "id": "should-not-appear", "position": "ghost"}
    payload = [legal_with_noise, _sample_job(7)]
    with patch("httpx.Client.get", return_value=_build_response(payload)):
        result = remoteok.fetch_remoteok_jobs()

    assert len(result) == 1
    assert result[0]["external_id"] == "remoteok-7"
    assert all(r["external_id"] != "should-not-appear" for r in result)


class TestParsing:
    # Test sui parser ISO datetime sono ora centralizzati in
    # ``test_integrations_common.py::test_parse_iso_datetime_*`` dopo
    # l'estrazione dell'helper in ``integrations._common``.
    def test_safe_int_handles_none_and_strings(self) -> None:
        assert remoteok._safe_int(None) is None
        assert remoteok._safe_int(80000) == 80000
        assert remoteok._safe_int("80000") == 80000
        assert remoteok._safe_int("not-a-number") is None
