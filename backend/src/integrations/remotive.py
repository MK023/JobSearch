"""Client API Remotive per il livello di ingest WorldWild.

Single responsibility: fetch + normalizzazione dei risultati Remotive in uno
schema ``dict`` piatto che il servizio di ingest WorldWild possa hashare,
deduplicare e persistere.

Out of scope: dedup cross-run, persistenza, pre-filter, AI analysis. Quelli
vivono in ``..worldwild.services.ingest`` per mantenere il client testabile
in isolamento.

Graceful degradation: lista vuota su errori di rete, 4xx/5xx, payload
malformato. I breadcrumb Sentry rendono visibile un adapter andato stale
senza far crashare il cron caller.

Note Remotive specifiche:
- nessuna autenticazione richiesta (API pubblica)
- nessuna paginazione: una sola response con parametro ``limit`` (default
  upstream 1500). Per questo non replichiamo il loop pagine di Adzuna
- ``salary`` arriva come stringa free-form (es. ``"$80,000-$120,000"``);
  proviamo un parse regex best-effort, fallback su ``None``
"""

import contextlib
from datetime import UTC, datetime
from typing import Any

import httpx

REMOTIVE_BASE = "https://remotive.com/api/remote-jobs"
DEFAULT_LIMIT = 200
DEFAULT_TIMEOUT_SECONDS = 15.0

# Parser salary range completamente non-regex: split su dash/en-dash + scan
# pure-python single-pass per estrarre il primo gruppo numerico da ogni
# segmento. Garantito linear (no backtracking possibile per costruzione).
_DASH_CHARS = ("–", "-")  # en-dash + ASCII dash


def _split_on_dash(text: str) -> list[str]:
    """Split lineare su dash/en-dash (singola passata, no regex)."""
    for ch in _DASH_CHARS:
        if ch in text:
            return text.split(ch, 1)
    return [text]


def _extract_first_number(text: str) -> str | None:
    """Single-pass scan per il primo gruppo digit+separatori. Return None se assente.

    Pattern lineare in ``len(text)``: itera una volta, marca inizio sui digit,
    interrompe sul primo carattere non numerico/non separatore. Zero rischio
    ReDoS (pure-python, no regex engine).
    """
    start = -1
    for i, c in enumerate(text):
        is_digit_or_sep = c.isdigit() or c in (",", ".", " ")
        if c.isdigit() and start < 0:
            start = i
        elif start >= 0 and not is_digit_or_sep:
            return text[start:i]
    return text[start:] if start >= 0 else None


def fetch_remotive_jobs(
    query: str = "",
    category: str = "",
    *,
    limit: int = DEFAULT_LIMIT,
    timeout_s: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """Fetch + normalizza i job Remotive.

    Ritorna una lista di dict normalizzati nello schema canonico WorldWild.
    Lista vuota su qualsiasi errore (network, 4xx/5xx, payload non valido):
    il caller la tratta come "questo run non ha prodotto nulla" anziché
    far crashare il cron.

    Parametri:
    - ``query``: keyword di ricerca full-text (vuoto = tutti i job)
    - ``category``: slug categoria Remotive (es. ``"software-dev"``)
    - ``limit``: numero massimo di job richiesti upstream
    - ``timeout_s``: timeout HTTP totale in secondi
    """
    params: dict[str, str | int] = {"limit": limit}
    if query:
        params["search"] = query
    if category:
        params["category"] = category

    try:
        raw_jobs = _fetch(params=params, timeout_s=timeout_s)
    except (httpx.HTTPError, ValueError) as exc:
        # Errore upstream: breadcrumb a Sentry e ritorno vuoto graceful.
        _record_error(exc)
        return []

    normalized: list[dict[str, Any]] = []
    for raw in raw_jobs:
        item = _normalize(raw)
        if item is not None:
            normalized.append(item)
    return normalized


def _fetch(*, params: dict[str, str | int], timeout_s: float) -> list[dict[str, Any]]:
    """Esegue la singola GET a Remotive e ritorna la lista ``jobs`` raw."""
    with httpx.Client(timeout=timeout_s) as client:
        resp = client.get(REMOTIVE_BASE, params=params)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        return []
    jobs = payload.get("jobs", [])
    return jobs if isinstance(jobs, list) else []


def _normalize(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Appiattisce un job Remotive nel canonical shape WorldWild.

    Ritorna ``None`` se mancano essenziali (id o title): righe inutili che
    sporcherebbero ``job_offers``.
    """
    ext_id = str(raw.get("id") or "").strip()
    title = (raw.get("title") or "").strip()
    if not ext_id or not title:
        return None

    salary_min, salary_max, salary_currency = _parse_salary(raw.get("salary"))

    return {
        "source": "remotive",
        "external_id": ext_id,
        "title": title[:500],
        "company": _safe_str(raw.get("company_name"), 255),
        "location": _safe_str(raw.get("candidate_required_location"), 255),
        "url": _safe_str(raw.get("url"), 1000),
        # Remotive serve description in HTML: la preserviamo come fa Adzuna,
        # rendering/sanitizzazione spettano al layer di presentation.
        "description": (raw.get("description") or "").strip(),
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_currency": salary_currency,
        # Remotive non distingue contract_type vs contract_time: usiamo
        # ``job_type`` (full_time/part_time/contract/freelance) come
        # contract_type, contract_time vuoto per non perdere mypy strict.
        "contract_type": _safe_str(raw.get("job_type"), 32),
        "contract_time": "",
        "category": _safe_str(raw.get("category"), 128),
        "posted_at": _parse_publication_date(raw.get("publication_date")),
        "raw_payload": raw,
    }


def _safe_str(value: Any, max_len: int) -> str:
    """Conversione sicura ``Any -> str`` con troncamento difensivo."""
    if value is None:
        return ""
    s = str(value).strip()
    return s[:max_len]


def _parse_salary(value: Any) -> tuple[int | None, int | None, str]:
    """Estrae (min, max, currency) dalla stringa salary free-form di Remotive.

    Esempi gestiti:
    - ``"$80,000-$120,000"`` → ``(80000, 120000, "USD")``
    - ``"80.000 – 120.000 EUR"`` → ``(80000, 120000, "EUR")``
    - ``"competitive"`` → ``(None, None, "")``
    - ``""`` / ``None`` → ``(None, None, "")``

    Best-effort: se la regex non matcha o i numeri non sono parsabili
    ritorna ``(None, None, "")`` senza sollevare.
    """
    if not value:
        return (None, None, "")
    text = str(value)

    # Split lineare su dash/en-dash. Se il salary non è un range
    # (es. "competitive", "100k starting"), ritorniamo subito.
    parts = _split_on_dash(text)
    if len(parts) < 2:
        return (None, None, "")

    raw_min = _extract_first_number(parts[0])
    raw_max = _extract_first_number(parts[1])
    if raw_min is None or raw_max is None:
        return (None, None, "")

    salary_min = _coerce_money(raw_min)
    salary_max = _coerce_money(raw_max)
    if salary_min is None or salary_max is None:
        return (None, None, "")

    currency = _infer_currency(text)
    return (salary_min, salary_max, currency)


def _coerce_money(token: str) -> int | None:
    """Rimuove separatori migliaia e converte in int. ``None`` se invalido."""
    cleaned = token.replace(",", "").replace(".", "")
    try:
        return int(cleaned)
    except ValueError:
        return None


def _infer_currency(text: str) -> str:
    """Inferenza valuta dai simboli più comuni; vuoto se ambiguo."""
    if "$" in text or "USD" in text.upper():
        return "USD"
    if "€" in text or "EUR" in text.upper():
        return "EUR"
    if "£" in text or "GBP" in text.upper():
        return "GBP"
    return ""


def _parse_publication_date(value: Any) -> datetime | None:
    """Parser ISO datetime per ``publication_date`` Remotive in UTC tz-aware.

    Remotive serve formato ISO 8601 (es. ``"2024-04-15T10:30:00"`` oppure con
    suffisso ``Z``). ``fromisoformat`` su 3.11+ gestisce entrambi una volta
    normalizzato il suffisso ``Z``. Naive datetimes vengono forzati a UTC.
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
    """Logga su Sentry senza far raise: mantiene il cron resiliente.

    Il wrap ``contextlib.suppress`` è il modo Pythonico per esprimere
    "swallow intenzionale": Sentry non è inizializzato in test/dev locale e
    non vogliamo che quello rimbalzi sul caller.
    """
    with contextlib.suppress(Exception):
        import sentry_sdk

        sentry_sdk.add_breadcrumb(
            category="remotive",
            message=f"remotive fetch failed: {type(exc).__name__}",
            level="warning",
        )
        sentry_sdk.capture_exception(exc)
