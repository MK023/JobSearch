"""Jobicy API client for the WorldWild ingest layer.

Single responsibility: fetch + normalize Jobicy remote-jobs results into a
flat ``dict`` schema that the WorldWild ingest service can hash, dedup, and
persist.

Out of scope: dedup, persistence, pre-filter, AI analysis. Those live in
``..worldwild.services.ingest`` per mantenere il client testabile in
isolamento.

Graceful degradation: lista vuota su errori di rete / 4xx / 5xx / payload
malformato. I breadcrumb Sentry rendono visibile un adapter che inizia a
fallire senza far esplodere il cron.

Note specifiche Jobicy:
- nessuna autenticazione, nessuna paginazione (un solo GET con ``count``)
- campo ``id`` numerico, ``pubDate`` senza timezone (assumiamo UTC)
- ``annualSalaryMin/Max`` arrivano come stringa nel JSON
- ``jobIndustry`` e ``jobType`` sono liste: prendiamo il primo elemento
"""

from typing import Any

import httpx

from ._common import parse_iso_datetime, record_error, safe_str

JOBICY_BASE = "https://jobicy.com/api/v2/remote-jobs"
DEFAULT_COUNT = 50  # Jobicy cap esplicito per call
HTTP_TIMEOUT_SECONDS = 15.0


def fetch_jobicy_jobs(
    *,
    count: int = DEFAULT_COUNT,
    geo: str = "",
    industry: str = "",
    tag: str = "",
    timeout_s: float = HTTP_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """Fetch + normalize jobs da Jobicy.

    Nessuna paginazione: ``count`` controlla quanti record l'endpoint
    restituisce in una sola GET (max 50 documentato). I filtri ``geo`` /
    ``industry`` / ``tag`` sono opzionali — se vuoti vengono omessi dalla
    query string per non vincolare lato server.

    Ritorna lista vuota su qualsiasi errore (network, status non-2xx,
    payload non parsabile) per non far cadere il cron di ingest.
    """
    params: dict[str, str | int] = {"count": count}
    if geo:
        params["geo"] = geo
    if industry:
        params["industry"] = industry
    if tag:
        params["tag"] = tag

    try:
        raw_jobs = _fetch(params=params, timeout_s=timeout_s)
    except (httpx.HTTPError, ValueError) as exc:
        record_error(exc, source="jobicy")
        return []

    normalized: list[dict[str, Any]] = []
    seen_external_ids: set[str] = set()
    for raw in raw_jobs:
        item = _normalize(raw)
        if item is None:
            continue
        ext_id = item["external_id"]
        if ext_id in seen_external_ids:
            continue
        seen_external_ids.add(ext_id)
        normalized.append(item)

    return normalized


def _fetch(*, params: dict[str, str | int], timeout_s: float) -> list[dict[str, Any]]:
    with httpx.Client(timeout=timeout_s) as client:
        resp = client.get(JOBICY_BASE, params=params)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        return []
    jobs = payload.get("jobs", [])
    return jobs if isinstance(jobs, list) else []


def _normalize(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Appiattisce un job Jobicy nello schema canonico WorldWild.

    Ritorna ``None`` quando mancano gli essenziali (id o titolo) — quei
    record sarebbero solo rumore in ``job_offers``.
    """
    ext_id = str(raw.get("id") or "").strip()
    title = (raw.get("jobTitle") or "").strip()
    if not ext_id or not title:
        return None

    return {
        "source": "jobicy",
        "external_id": ext_id,
        "title": title[:500],
        "company": safe_str(raw.get("companyName"), 255),
        "location": safe_str(raw.get("jobGeo"), 255),
        "url": safe_str(raw.get("url"), 1000),
        "description": (raw.get("jobDescription") or "").strip(),
        "salary_min": _safe_int(raw.get("annualSalaryMin")),
        "salary_max": _safe_int(raw.get("annualSalaryMax")),
        "salary_currency": safe_str(raw.get("salaryCurrency"), 8),
        "contract_type": _normalize_contract_type(raw.get("jobType")),
        "category": _first_of_list(raw.get("jobIndustry"), max_len=128),
        "posted_at": parse_iso_datetime(raw.get("pubDate")),
        "raw_payload": raw,
    }


def _safe_int(value: Any) -> int | None:
    """Tollera ``None``, interi, e stringhe numeriche (Jobicy serializza i salari come stringa)."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_of_list(value: Any, *, max_len: int) -> str:
    """Estrae il primo elemento di una lista come stringa, o ``""``."""
    if not isinstance(value, list) or not value:
        return ""
    first = value[0]
    return safe_str(first, max_len)


def _normalize_contract_type(value: Any) -> str:
    """Converte ``["full-time"]`` → ``"full_time"`` per coerenza con Adzuna."""
    raw = _first_of_list(value, max_len=32)
    return raw.replace("-", "_").lower() if raw else ""
