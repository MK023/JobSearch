"""Client API Working Nomads per il layer di ingest WorldWild.

Single responsibility: fetch + normalize dei risultati dell'endpoint pubblico
Working Nomads in dict piatti, pronti per il servizio di ingest WorldWild
(che gestira' hashing, dedup e persistence).

Out of scope: dedup, persistence, pre-filter, AI analysis. Restano in
``..worldwild.services.ingest`` per mantenere il client testabile in isolamento.

Graceful degradation: lista vuota su errori di rete o risposte malformate.
Sentry breadcrumb sui non-2xx cosi' un adapter che si rompe diventa visibile
senza far esplodere la cron.

Differenze rispetto ad Adzuna:
- nessuna autenticazione (endpoint pubblico)
- nessuna paginazione: l'API ritorna un array JSON top-level (~few hundred jobs)
- nessun salary, nessun contract_type esplicito
- ``tags`` e' una stringa virgola-separata (non un array)
- ``id`` non esposto: usiamo ``url`` come external_id (stabile cross-poll)
"""

from typing import Any

import httpx

from ._common import parse_iso_datetime, record_error, safe_str

WORKINGNOMADS_ENDPOINT = "https://www.workingnomads.com/api/exposed_jobs/"
HTTP_TIMEOUT_SECONDS = 15.0


def fetch_workingnomads_jobs(
    *,
    category_filter: str = "",
    timeout_s: float = HTTP_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """Fetch + normalize delle offerte Working Nomads.

    Single response, niente paginazione. ``category_filter`` (se valorizzato)
    e' un substring match case-insensitive su ``category_name`` applicato
    client-side dopo il fetch — Working Nomads non espone un parametro
    ``category`` server-side.

    Returns:
        Lista di dict normalizzati. Lista vuota su errori HTTP, payload
        malformato o nessun match con il ``category_filter``.
    """
    try:
        raw_items = _fetch_all(timeout_s=timeout_s)
    except (httpx.HTTPError, ValueError) as exc:
        record_error(exc, source="workingnomads")
        return []

    aggregated: list[dict[str, Any]] = []
    needle = category_filter.strip().lower()

    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        if needle and needle not in str(raw.get("category_name", "")).lower():
            continue
        normalized = _normalize(raw)
        if normalized is not None:
            aggregated.append(normalized)

    return aggregated


def _fetch_all(*, timeout_s: float) -> list[dict[str, Any]]:
    """Single HTTP GET — Working Nomads ritorna un array JSON top-level."""
    with httpx.Client(timeout=timeout_s) as client:
        resp = client.get(WORKINGNOMADS_ENDPOINT)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, list):
        return []
    return payload


def _normalize(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Appiattisce un job Working Nomads nello schema canonico WorldWild.

    Returns ``None`` se mancano gli essenziali (url o title): inutili nel DB.
    """
    ext_id = safe_str(raw.get("url"), 1000)
    title = safe_str(raw.get("title"), 500)
    if not ext_id or not title:
        return None

    location = safe_str(raw.get("location"), 255) or safe_str(raw.get("country"), 255)

    return {
        "source": "workingnomads",
        "external_id": ext_id,
        "title": title,
        "company": safe_str(raw.get("company_name"), 255),
        "location": location,
        "url": ext_id,
        "description": (raw.get("description") or "").strip(),
        "salary_min": None,
        "salary_max": None,
        "salary_currency": "",
        "contract_type": "",
        "contract_time": "",
        "category": safe_str(raw.get("category_name"), 128),
        "posted_at": parse_iso_datetime(raw.get("pub_date")),
        "raw_payload": raw,
    }
