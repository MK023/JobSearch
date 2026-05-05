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

import contextlib
from datetime import UTC, datetime
from typing import Any

import httpx

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
        _record_error(exc)
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
    ext_id = _safe_str(raw.get("url"), 1000)
    title = _safe_str(raw.get("title"), 500)
    if not ext_id or not title:
        return None

    location = _safe_str(raw.get("location"), 255) or _safe_str(raw.get("country"), 255)

    return {
        "source": "workingnomads",
        "external_id": ext_id,
        "title": title,
        "company": _safe_str(raw.get("company_name"), 255),
        "location": location,
        "url": ext_id,
        "description": (raw.get("description") or "").strip(),
        "salary_min": None,
        "salary_max": None,
        "salary_currency": "",
        "contract_type": "",
        "contract_time": "",
        "category": _safe_str(raw.get("category_name"), 128),
        "posted_at": _parse_pub_date(raw.get("pub_date")),
        "raw_payload": raw,
    }


def _safe_str(value: Any, max_len: int) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    return s[:max_len]


def _parse_pub_date(value: Any) -> datetime | None:
    """Parse della stringa ISO ``pub_date`` in datetime UTC-aware.

    Working Nomads usa formato ``2024-06-01T10:30:00Z``.
    """
    if not value:
        return None
    try:
        normalized = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (TypeError, ValueError):
        return None


def _record_error(exc: Exception) -> None:
    """Log su Sentry senza rilanciare — mantiene la cron resiliente.

    ``contextlib.suppress`` e' il modo Pythonico per esprimere "swallow
    intenzionale": Sentry non e' inizializzato in test/dev locale e non
    vogliamo che la mancanza torni indietro al chiamante.
    """
    with contextlib.suppress(Exception):
        import sentry_sdk

        # Solo breadcrumb (no capture_exception): errori upstream graceful, già gestiti con return [] graceful. Niente issue spam su Sentry per degraded service vendor.
        sentry_sdk.add_breadcrumb(
            category="workingnomads",
            message=f"workingnomads fetch failed: {type(exc).__name__}",
            level="warning",
        )
