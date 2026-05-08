"""Arbeitnow API client for the WorldWild ingest layer.

Single responsibility: fetch + normalize Arbeitnow job-board results into a
flat ``dict`` schema that the WorldWild ingest service can hash, dedup, and
persist.

Out of scope: dedup, persistence, pre-filter, AI analysis. Those live in
``..worldwild.services.ingest`` to keep the client testable in isolation.

Graceful degradation: empty list on network errors, 4xx/5xx, or malformed
payloads. Sentry breadcrumbs on non-2xx so an adapter going stale becomes
visible without raising.

Endpoint: ``GET https://www.arbeitnow.com/api/job-board-api?page={N}``.
No auth required. Page-based pagination with ``meta.last_page`` to know when
to stop. Arbeitnow exposes a ``remote`` boolean flag, useful for filtering
client-side since Marco's target is remote-first.
"""

from datetime import UTC, datetime
from typing import Any

import httpx

from ._common import record_error, safe_str

ARBEITNOW_BASE = "https://www.arbeitnow.com/api/job-board-api"
DEFAULT_MAX_PAGES = 5  # ~10 results/page typically — 50 results/run is plenty
DEFAULT_TIMEOUT_SECONDS = 15.0


def fetch_arbeitnow_jobs(
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
    remote_only: bool = True,
    timeout_s: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """Recupera + normalizza le offerte Arbeitnow.

    Paginazione page-based: si incrementa ``page`` fino a ``max_pages`` o fino
    a quando ``meta.last_page`` indica che siamo all'ultima pagina disponibile.

    Il filtro ``remote_only`` è applicato client-side (Arbeitnow non offre un
    parametro server-side per questo) post-fetch: se ``item["remote"]`` è
    falsy l'item viene scartato in fase di normalizzazione.

    Ritorna una lista (possibilmente vuota) di dict normalizzati. Mai solleva
    eccezioni: in caso di errore HTTP/parse interrompe la paginazione e
    restituisce ciò che ha già raccolto.
    """
    aggregated: list[dict[str, Any]] = []
    seen_external_ids: set[str] = set()

    for page in range(1, max_pages + 1):
        try:
            page_results, last_page = _fetch_page(page=page, timeout_s=timeout_s)
        except (httpx.HTTPError, ValueError) as exc:
            record_error(exc, source="arbeitnow", page=page)
            break

        if not page_results:
            break

        for raw in page_results:
            normalized = _normalize(raw, remote_only=remote_only)
            if normalized is None:
                continue
            ext_id = normalized["external_id"]
            if ext_id in seen_external_ids:
                continue
            seen_external_ids.add(ext_id)
            aggregated.append(normalized)

        # Arbeitnow espone ``meta.last_page``: smettiamo se l'abbiamo raggiunta.
        if last_page is not None and page >= last_page:
            break

    return aggregated


def _fetch_page(*, page: int, timeout_s: float) -> tuple[list[dict[str, Any]], int | None]:
    """Esegue una singola GET su Arbeitnow per ``page``.

    Ritorna ``(data, last_page)`` dove ``last_page`` è l'ultimo numero di
    pagina disponibile (``meta.last_page``) oppure ``None`` se non presente.
    """
    params: dict[str, str | int] = {"page": page}
    with httpx.Client(timeout=timeout_s) as client:
        resp = client.get(ARBEITNOW_BASE, params=params)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        return [], None

    raw_data = payload.get("data", [])
    data: list[dict[str, Any]] = raw_data if isinstance(raw_data, list) else []

    meta = payload.get("meta") or {}
    last_page_raw = meta.get("last_page") if isinstance(meta, dict) else None
    last_page: int | None
    try:
        last_page = int(last_page_raw) if last_page_raw is not None else None
    except (TypeError, ValueError):
        last_page = None

    return data, last_page


def _normalize(raw: dict[str, Any], *, remote_only: bool) -> dict[str, Any] | None:
    """Appiattisce un risultato Arbeitnow nello schema canonico WorldWild.

    Ritorna ``None`` quando:
    - mancano campi essenziali (``slug`` o ``title``)
    - ``remote_only=True`` e l'item non è remoto

    Note di mapping:
    - Arbeitnow non espone ``category`` né ``salary``: rimangono vuoti/None.
    - ``job_types`` è una lista di stringhe (es. ``["full-time"]``); prendiamo
      la prima e normalizziamo trattini in underscore (``full-time`` →
      ``full_time``) per coerenza con altri client (es. Adzuna).
    - ``created_at`` è un Unix timestamp; lo convertiamo in datetime UTC.
    """
    ext_id = str(raw.get("slug") or "").strip()
    title = (raw.get("title") or "").strip()
    if not ext_id or not title:
        return None

    if remote_only and not raw.get("remote"):
        return None

    job_types_raw = raw.get("job_types") or []
    job_types: list[Any] = job_types_raw if isinstance(job_types_raw, list) else []
    contract_type = ""
    if job_types:
        first = str(job_types[0] or "").strip()
        contract_type = first.replace("-", "_")

    return {
        "source": "arbeitnow",
        "external_id": ext_id,
        "title": title[:500],
        "company": safe_str(raw.get("company_name"), 255),
        "location": safe_str(raw.get("location"), 255),
        "url": safe_str(raw.get("url"), 1000),
        "description": (raw.get("description") or "").strip(),
        "salary_min": None,
        "salary_max": None,
        "salary_currency": "",
        "contract_type": contract_type[:32],
        "contract_time": "",
        "category": "",
        "posted_at": _parse_created_at(raw.get("created_at")),
        "raw_payload": raw,
    }


def _parse_created_at(value: Any) -> datetime | None:
    """Converte il timestamp Unix Arbeitnow in datetime UTC.

    Arbeitnow ritorna ``created_at`` come secondi-da-epoch (int). Tolleriamo
    anche stringhe numeriche per robustezza. Ritorna ``None`` su input
    invalidi (None, stringhe non numeriche, overflow, ecc.).
    """
    if value is None or value == "":
        return None
    try:
        ts = int(value)
        return datetime.fromtimestamp(ts, tz=UTC)
    except (TypeError, ValueError, OSError, OverflowError):
        return None
