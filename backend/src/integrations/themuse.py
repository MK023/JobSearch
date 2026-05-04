"""The Muse API client per il layer di ingest WorldWild.

Single responsibility: fetch + normalizzazione dei risultati di The Muse in uno
schema piatto ``dict`` che il servizio di ingest WorldWild puo' hashare,
deduplicare e persistere.

Out of scope: dedup, persistence, pre-filter, AI analysis (vivono in
``..worldwild.services.ingest`` per mantenere il client testabile in isolamento).

Graceful degradation: lista vuota su errori di rete o 4xx/5xx. Sentry breadcrumb
sui non-2xx cosi' un adapter che si rompe diventa visibile senza far esplodere
la cron.

API ref: https://www.themuse.com/developers/api/v2
- No auth obbligatoria; ``api_key`` opzionale aumenta il rate limit
  (free senza key ~60 req/h).
- Pagination page-based, 20 risultati/pagina; il payload espone ``page_count``.
- Salary non e' esposto da The Muse → restituiamo None / "".
"""

import contextlib
from datetime import UTC, datetime
from typing import Any

import httpx

THEMUSE_BASE = "https://www.themuse.com/api/public/jobs"
HTTP_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_PAGES = 5


def fetch_themuse_jobs(
    category: str = "",
    location: str = "",
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
    api_key: str = "",
    timeout_s: float = HTTP_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """Fetch + normalizza i job di The Muse. Pagination page-based.

    ``category`` e ``location`` sono filtri opzionali lato API (es. "Engineering",
    "Remote"). Stringa vuota = nessun filtro su quel campo.

    ``api_key`` opzionale alza il rate limit; senza key The Muse permette ~60
    req/h. ``max_pages`` cappa la paginazione (default 5 = max 100 risultati/run).

    Ritorna lista vuota su qualsiasi errore (network, 4xx/5xx, JSON malformato).
    """
    aggregated: list[dict[str, Any]] = []
    seen_external_ids: set[str] = set()

    page = 1
    while page <= max_pages:
        try:
            payload = _fetch_page(
                category=category,
                location=location,
                page=page,
                api_key=api_key,
                timeout_s=timeout_s,
            )
        except (httpx.HTTPError, ValueError) as exc:
            _record_error(exc, page=page)
            break

        results = payload.get("results", [])
        if not isinstance(results, list) or not results:
            break

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

        # The Muse espone page_count: stop quando abbiamo letto l'ultima pagina.
        page_count_raw = payload.get("page_count")
        try:
            page_count = int(page_count_raw) if page_count_raw is not None else 0
        except (TypeError, ValueError):
            page_count = 0
        if page_count and page >= page_count:
            break

        page += 1

    return aggregated


def _fetch_page(
    *,
    category: str,
    location: str,
    page: int,
    api_key: str,
    timeout_s: float,
) -> dict[str, Any]:
    params: dict[str, str | int] = {"page": page}
    if category:
        params["category"] = category
    if location:
        params["location"] = location
    if api_key:
        params["api_key"] = api_key

    with httpx.Client(timeout=timeout_s) as client:
        resp = client.get(THEMUSE_BASE, params=params)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        return {}
    return payload


def _normalize(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Appiattisce un risultato The Muse nello schema canonico WorldWild.

    Ritorna ``None`` quando mancano gli essenziali (id o title), per evitare
    spazzatura inutile in ``job_offers``.
    """
    ext_id = str(raw.get("id") or "").strip()
    title = (raw.get("name") or "").strip()
    if not ext_id or not title:
        return None

    company_raw = raw.get("company") or {}
    refs_raw = raw.get("refs") or {}

    locations = raw.get("locations") or []
    location_str = ", ".join(loc.get("name", "") for loc in locations if isinstance(loc, dict) and loc.get("name"))

    categories = raw.get("categories") or []
    category = ""
    if categories and isinstance(categories[0], dict):
        category = (categories[0].get("name") or "").strip()

    contract_type = (raw.get("type") or "").strip().lower().replace("-", "_")

    return {
        "source": "themuse",
        "external_id": ext_id,
        "title": title[:500],
        "company": _safe_str(company_raw.get("name") if isinstance(company_raw, dict) else "", 255),
        "location": location_str[:255],
        "url": _safe_str(refs_raw.get("landing_page") if isinstance(refs_raw, dict) else "", 1000),
        "description": (raw.get("contents") or "").strip(),
        "salary_min": None,
        "salary_max": None,
        "salary_currency": "",
        "contract_type": contract_type[:32],
        "category": category[:128],
        "posted_at": _parse_publication_date(raw.get("publication_date")),
        "raw_payload": raw,
    }


def _safe_str(value: Any, max_len: int) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    return s[:max_len]


def _parse_publication_date(value: Any) -> datetime | None:
    """Parse il datetime ISO di The Muse in datetime UTC tz-aware.

    Formato tipico: ``"2024-06-01T10:30:00.000Z"``.
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


def _record_error(exc: Exception, *, page: int) -> None:
    """Log a Sentry senza propagare — mantiene la cron resiliente.

    ``contextlib.suppress`` e' il modo Pythonico per dire "swallow intenzionale":
    Sentry non e' inizializzato in test/local dev, e non vogliamo che sia un
    problema per il caller.
    """
    with contextlib.suppress(Exception):
        import sentry_sdk

        sentry_sdk.add_breadcrumb(
            category="themuse",
            message=f"themuse fetch failed page={page}: {type(exc).__name__}",
            level="warning",
        )
        sentry_sdk.capture_exception(exc)
