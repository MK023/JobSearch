"""Client API Remote OK per il layer di ingest WorldWild.

Singola responsabilità: fetch + normalizzazione dei risultati Remote OK in uno
schema flat (``dict``) che il servizio di ingest WorldWild può poi hashare,
deduplicare e persistere.

Fuori scope: dedup, persistenza, pre-filtro, analisi AI. Vivono in
``..worldwild.services.ingest`` per mantenere il client testabile in isolamento.

Particolarità Remote OK:
- Endpoint pubblico ``GET https://remoteok.com/api`` senza autenticazione.
- ``User-Agent`` custom **obbligatorio**: il default ``python-httpx/x.y`` viene
  bloccato (403). Identifichiamoci come ``Worldwild/1.0``.
- Il primo elemento dell'array è un disclaimer legale (chiave ``"legal"``) e va
  filtrato — non è un job.
- Nessuna paginazione: singola response con ~250 risultati.
- Salari sempre in USD (de facto), nessun campo currency esplicito.

Degradazione graceful: lista vuota su errori di rete o 4xx/5xx. Le rotture
upstream finiscono in Sentry come breadcrumb, senza propagare al cron caller.
"""

import contextlib
from datetime import UTC, datetime
from typing import Any

import httpx

REMOTEOK_BASE = "https://remoteok.com/api"
USER_AGENT = "Worldwild/1.0 (+https://github.com/MK023/JobSearch)"
HTTP_TIMEOUT_SECONDS = 15.0


def fetch_remoteok_jobs(
    tags: tuple[str, ...] = (),
    *,
    timeout_s: float = HTTP_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """Recupera e normalizza i job da Remote OK.

    Args:
        tags: tuple di tag da filtrare (es. ``("devops", "python")``). Vengono
            uniti con virgola nel query param ``tags`` come richiesto dall'API.
            Tuple vuota = nessun filtro (tutti i job).
        timeout_s: timeout HTTP totale in secondi.

    Returns:
        Lista di dict normalizzati nello schema canonico WorldWild. Lista vuota
        in caso di errori di rete, status non-2xx, payload malformato o solo
        disclaimer legale.

    Note:
        L'header ``User-Agent`` custom è obbligatorio: senza, Remote OK risponde
        ``403 Forbidden``. Il default ``python-httpx/x.y`` è blacklistato.
    """
    params: dict[str, str] = {}
    if tags:
        params["tags"] = ",".join(tags)

    headers = {"User-Agent": USER_AGENT}

    try:
        with httpx.Client(timeout=timeout_s, headers=headers) as client:
            resp = client.get(REMOTEOK_BASE, params=params)
        resp.raise_for_status()
        payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        _record_error(exc)
        return []

    if not isinstance(payload, list):
        return []

    aggregated: list[dict[str, Any]] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        # Il primo item (e solo il primo, di solito) è il disclaimer legale:
        # ``{"legal": "Remote OK API ..."}``. Va saltato senza far rumore.
        if "legal" in raw:
            continue
        normalized = _normalize(raw)
        if normalized is None:
            continue
        aggregated.append(normalized)

    return aggregated


def _normalize(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Appiattisce un job Remote OK nello schema canonico WorldWild.

    Ritorna ``None`` quando mancano gli essenziali (id o titolo): finirebbero
    come spazzatura inutile in ``job_offers``.
    """
    ext_id = str(raw.get("id") or "").strip()
    title = (raw.get("position") or "").strip()
    if not ext_id or not title:
        return None

    salary_min = _safe_int(raw.get("salary_min"))
    salary_max = _safe_int(raw.get("salary_max"))
    # Remote OK è USD-only de facto; popoliamo currency solo quando abbiamo
    # almeno un valore salariale, così downstream sa che il valore è
    # interpretabile.
    salary_currency = "USD" if (salary_min is not None or salary_max is not None) else ""

    return {
        "source": "remoteok",
        "external_id": ext_id,
        "title": title[:500],
        "company": _safe_str(raw.get("company"), 255),
        "location": _safe_str(raw.get("location"), 255),
        "url": _safe_str(raw.get("url") or raw.get("apply_url"), 1000),
        "description": (raw.get("description") or "").strip(),
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_currency": salary_currency,
        "contract_type": "",  # non esposto dall'API
        "category": "",  # Remote OK usa solo ``tags``, no campo category
        "posted_at": _parse_date(raw.get("date")),
        "raw_payload": raw,
    }


def _safe_str(value: Any, max_len: int) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    return s[:max_len]


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> datetime | None:
    """Parsa il campo ``date`` ISO 8601 di Remote OK in datetime tz-aware UTC."""
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
    """Logga su Sentry senza rilanciare — mantiene il cron resiliente.

    ``contextlib.suppress`` esprime in modo Pythonic "ignoro intenzionalmente":
    Sentry non è inizializzato in test/local dev, e non vogliamo che questa
    fragilità rimbalzi sul caller.
    """
    with contextlib.suppress(Exception):
        import sentry_sdk

        sentry_sdk.add_breadcrumb(
            category="remoteok",
            message=f"remoteok fetch failed: {type(exc).__name__}",
            level="warning",
        )
        sentry_sdk.capture_exception(exc)
