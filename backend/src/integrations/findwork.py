"""Findwork.dev API client per il layer di ingest WorldWild.

Single responsibility: fetch + normalizzazione delle search results di
Findwork in dict piatti che ``..worldwild.services.ingest`` può poi
hashare, deduplicare e persistere.

Out of scope: dedup, persistenza, pre-filter, AI analysis. Vivono nel
service di ingest per mantenere il client testabile in isolamento.

Graceful degradation: lista vuota su API key mancante, errori di rete,
4xx/5xx (incluso 401 non autorizzato). I breadcrumb Sentry rendono
visibili gli adapter andati stale senza far crashare il cron.
"""

import contextlib
from typing import Any

import httpx

from ..config import settings
from ._common import parse_iso_datetime, record_error, safe_str

FINDWORK_BASE = "https://findwork.dev/api/jobs/"
DEFAULT_MAX_PAGES = 5  # cursor-based; conservativo sul free tier
HTTP_TIMEOUT_SECONDS = 15.0


def fetch_findwork_jobs(
    search: str = "",
    location: str = "",
    *,
    remote: bool | None = True,
    max_pages: int = DEFAULT_MAX_PAGES,
    timeout_s: float = HTTP_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """Fetch + normalize Findwork jobs.

    Auth obbligatoria via ``FINDWORK_API_KEY`` (header ``Authorization:
    Token <key>``). Quando la key non è configurata ritorna ``[]`` con
    breadcrumb Sentry informativo, così il cron WorldWild può girare
    senza schiantarsi prima che Marco abbia ottenuto l'access token.

    ``remote=True`` filtra solo offerte remote (default coerente con il
    target Marco). Passare ``None`` per non filtrare.
    """
    api_key = settings.findwork_api_key
    if not api_key:
        _record_missing_key()
        return []

    aggregated: list[dict[str, Any]] = []
    seen_external_ids: set[str] = set()

    headers = {"Authorization": f"Token {api_key}"}
    initial_params: dict[str, str] = {}
    if search:
        initial_params["search"] = search
    if location:
        initial_params["location"] = location
    if remote is not None:
        initial_params["remote"] = "true" if remote else "false"

    next_url: str | None = FINDWORK_BASE
    next_params: dict[str, str] | None = initial_params
    pages_fetched = 0

    while next_url is not None and pages_fetched < max_pages:
        try:
            payload = _fetch_page(
                url=next_url,
                params=next_params,
                headers=headers,
                timeout_s=timeout_s,
            )
        except (httpx.HTTPError, ValueError) as exc:
            record_error(exc, source="findwork", page=pages_fetched + 1)
            break

        results = payload.get("results", [])
        if isinstance(results, list):
            for raw in results:
                if not isinstance(raw, dict):
                    continue
                normalized = _normalize(raw)
                if normalized is None:
                    continue
                ext_id = normalized["external_id"]
                if ext_id in seen_external_ids:
                    continue
                seen_external_ids.add(ext_id)
                aggregated.append(normalized)

        pages_fetched += 1

        # Cursor-based pagination: ``next`` è un URL completo (già
        # comprensivo dei query param), ``None`` sull'ultima pagina.
        raw_next = payload.get("next")
        next_url = raw_next if isinstance(raw_next, str) and raw_next else None
        # Sui follow-up il cursore embedda già tutti i parametri.
        next_params = None

    return aggregated


def _fetch_page(
    *,
    url: str,
    params: dict[str, str] | None,
    headers: dict[str, str],
    timeout_s: float,
) -> dict[str, Any]:
    with httpx.Client(timeout=timeout_s) as client:
        resp = client.get(url, params=params, headers=headers)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        return {}
    return payload


def _normalize(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Appiattisce un job Findwork nello shape canonico WorldWild.

    Ritorna ``None`` quando mancano gli essentials (no id o no role) —
    sarebbero spazzatura inutile in ``job_offers``.
    """
    ext_id = str(raw.get("id") or "").strip()
    title = (raw.get("role") or "").strip()
    if not ext_id or not title:
        return None

    employment_type_raw = raw.get("employment_type") or ""
    contract_type = str(employment_type_raw).strip().lower().replace(" ", "_")

    return {
        "source": "findwork",
        "external_id": ext_id,
        "title": title[:500],
        "company": safe_str(raw.get("company_name"), 255),
        "location": safe_str(raw.get("location"), 255),
        "url": safe_str(raw.get("url"), 1000),
        "description": (raw.get("text") or "").strip(),
        "salary_min": None,
        "salary_max": None,
        "salary_currency": "",
        "contract_type": contract_type[:32],
        "contract_time": "",
        "category": "",
        "posted_at": parse_iso_datetime(raw.get("date_posted")),
        "raw_payload": raw,
    }


def _record_missing_key() -> None:
    """Sentry breadcrumb informativo (non un errore) quando la key manca.

    Marco non ha ancora la API key Findwork: lasciamo il cron silenzioso
    ma tracciato, così quando configurerà la chiave vediamo il flip nel
    breadcrumb stream.
    """
    with contextlib.suppress(Exception):
        import sentry_sdk  # type: ignore[import-not-found]  # pyright: ignore[reportMissingImports]

        sentry_sdk.add_breadcrumb(
            category="findwork",
            message="Findwork API key not configured — skipping fetch",
            level="info",
        )
