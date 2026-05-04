"""Client We Work Remotely (RSS) per il layer ingest WorldWild.

Single responsibility: fetch + normalizzazione del feed RSS di We Work Remotely
(`weworkremotely.com`) in dict piatti compatibili con lo schema canonico
WorldWild, pronti per dedup/persist nel servizio ingest.

Out of scope: dedup, persistence, pre-filter, AI analysis. Tutto downstream.

Graceful degradation: lista vuota su errori di rete, 4xx/5xx, RSS malformato
o feed senza entry. Sentry breadcrumb su fallimento per visibilità senza
sollevare eccezioni al caller (mantiene il cron resiliente).

Endpoint: ``GET https://weworkremotely.com/categories/{category}/jobs.rss``.
No auth, nessuna paginazione (RSS standard ritorna ultimi N item).

Note di mapping:
- Il ``title`` WWR ha pattern ``"COMPANY: ROLE"`` → splittiamo sul primo
  ``:`` per estrarre company e titolo puliti.
- WWR è remote-only by design: ``location = "Remote"`` cablato.
- ``salary_*`` non sono esposti dal feed → None / "".
- ``raw_payload`` è il dict piatto di feedparser (FeedParserDict castata
  via ``dict()`` per serializzabilità JSON sicura).
"""

import contextlib
import re
from datetime import UTC, datetime
from typing import Any

import feedparser  # type: ignore[import-untyped]
import httpx

WWR_BASE = "https://weworkremotely.com/categories"
DEFAULT_CATEGORY = "remote-devops-sysadmin-jobs"
DEFAULT_TIMEOUT_SECONDS = 15.0

# Pattern "COMPANY: ROLE" — non-greedy sul gruppo company, prende tutto il
# resto come role. Ancorato sull'inizio per evitare match su ``:`` interni
# al titolo (es. "Senior DevOps: K8s & Terraform" senza company prefix).
_TITLE_SPLIT_RE = re.compile(r"^([^:]+):\s*(.+)$")


def fetch_weworkremotely_jobs(
    category: str = DEFAULT_CATEGORY,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """Recupera + normalizza il feed RSS di We Work Remotely per ``category``.

    Default category: ``remote-devops-sysadmin-jobs`` (allineato al target
    Cloud/DevOps/DevSecOps di Marco). Altre categorie disponibili lato WWR:
    ``remote-programming-jobs``, ``remote-design-jobs``, ecc.

    Esegue una singola GET HTTP via ``httpx`` (consistente con gli altri
    client del modulo ``integrations/``) e poi parsifica il body con
    ``feedparser``. Mai solleva: in caso di errore HTTP/parse ritorna ``[]``
    e logga un breadcrumb su Sentry.
    """
    url = f"{WWR_BASE}/{category}/jobs.rss"

    try:
        with httpx.Client(timeout=timeout_s) as client:
            resp = client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        _record_error(exc, category=category)
        return []

    # feedparser è permissivo: su XML malformato ritorna comunque un feed con
    # ``entries=[]`` e ``bozo=1``. Lo trattiamo come "nessun risultato" senza
    # raise, coerente con la policy di graceful degradation.
    parsed = feedparser.parse(resp.text)
    entries = getattr(parsed, "entries", []) or []
    if not isinstance(entries, list):
        return []

    aggregated: list[dict[str, Any]] = []
    seen_external_ids: set[str] = set()

    for entry in entries:
        normalized = _normalize(entry)
        if normalized is None:
            continue
        ext_id = normalized["external_id"]
        if ext_id in seen_external_ids:
            continue
        seen_external_ids.add(ext_id)
        aggregated.append(normalized)

    return aggregated


def _normalize(entry: Any) -> dict[str, Any] | None:
    """Appiattisce un entry RSS WWR nello schema canonico WorldWild.

    Ritorna ``None`` se mancano essenziali (no link, no title): senza
    ``external_id`` o ``title`` la riga sarebbe spazzatura in ``job_offers``.

    feedparser espone l'entry come ``FeedParserDict`` (dict-like con accesso
    via attributo o chiave). Usiamo ``.get()`` per robustezza su feed
    parziali/non-standard.
    """
    raw_title = (_get(entry, "title") or "").strip()
    link = (_get(entry, "link") or "").strip()
    if not raw_title or not link:
        return None

    # External ID: preferiamo ``id`` (guid RSS, sempre univoco quando presente)
    # con fallback sul ``link`` (anch'esso univoco per definizione su WWR).
    ext_id = (_get(entry, "id") or link).strip()
    if not ext_id:
        return None

    # Split "COMPANY: ROLE" — tipico pattern WWR. Se non matcha (titolo senza
    # ``:`` o senza company prefix), lasciamo company vuoto e usiamo il titolo
    # raw così com'è.
    match = _TITLE_SPLIT_RE.match(raw_title)
    if match:
        company = match.group(1).strip()
        title_clean = match.group(2).strip()
    else:
        company = ""
        title_clean = raw_title

    # Categoria: feedparser parsifica i ``<category>`` RSS in ``entry.tags``,
    # una lista di oggetti con attributo ``.term``. Prendiamo solo il primo
    # per coerenza con altri client (Adzuna espone una categoria singola).
    category_label = ""
    tags = _get(entry, "tags") or []
    if isinstance(tags, list) and tags:
        first_tag = tags[0]
        category_label = (_get(first_tag, "term") or "").strip()

    # Description HTML: WWR usa ``summary`` (alias di ``description``) per il
    # body. feedparser normalizza entrambi sotto ``summary``.
    description = (_get(entry, "summary") or _get(entry, "description") or "").strip()

    return {
        "source": "weworkremotely",
        "external_id": ext_id[:255],
        "title": title_clean[:500],
        "company": company[:255],
        "location": "Remote",  # WWR è remote-only by design
        "url": link[:1000],
        "description": description,
        "salary_min": None,
        "salary_max": None,
        "salary_currency": "",
        "contract_type": "",
        "contract_time": "",
        "category": category_label[:128],
        "posted_at": _parse_published(entry),
        "raw_payload": _to_plain_dict(entry),
    }


def _get(entry: Any, key: str) -> Any:
    """Accesso difensivo su FeedParserDict (dict-like ma con quirk)."""
    if entry is None:
        return None
    if isinstance(entry, dict):
        return entry.get(key)
    return getattr(entry, key, None)


def _parse_published(entry: Any) -> datetime | None:
    """Converte ``published_parsed`` (time.struct_time) in datetime UTC.

    feedparser espone la data RFC 822 di RSS come tuple di 9 elementi in
    ``published_parsed`` (UTC by spec). Usiamo i primi 6 (anno..secondi) per
    costruire il datetime e applichiamo ``tzinfo=UTC`` esplicitamente.

    Ritorna ``None`` su entry senza data o struttura inattesa.
    """
    parsed = _get(entry, "published_parsed")
    if parsed is None:
        return None
    try:
        # struct_time è indicizzabile come tuple su [0..8]
        return datetime(
            parsed[0],
            parsed[1],
            parsed[2],
            parsed[3],
            parsed[4],
            parsed[5],
            tzinfo=UTC,
        )
    except (TypeError, ValueError, IndexError):
        return None


def _to_plain_dict(entry: Any) -> dict[str, Any]:
    """Converte FeedParserDict in dict puro per serializzabilità.

    FeedParserDict è dict-like ma può contenere oggetti annidati non-JSON
    (es. ``time.struct_time``). Applichiamo una conversione superficiale
    che preserva chiavi/valori semplici e stringa-fica i casi opachi.
    """
    if isinstance(entry, dict):
        plain: dict[str, Any] = {}
        for k, v in entry.items():
            plain[str(k)] = _serializable(v)
        return plain
    return {}


def _serializable(value: Any) -> Any:
    """Best-effort: rende ``value`` JSON-friendly senza perdere info utili."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serializable(v) for v in value]
    return str(value)


def _record_error(exc: Exception, *, category: str) -> None:
    """Logga su Sentry senza sollevare — mantiene il cron resiliente.

    ``contextlib.suppress`` esprime in modo Pythonico l'intento "ingoia
    intenzionalmente": Sentry non è inizializzato in test/local dev e non
    vogliamo che il fallimento di logging rimbalzi sul caller.
    """
    with contextlib.suppress(Exception):
        import sentry_sdk

        sentry_sdk.add_breadcrumb(
            category="weworkremotely",
            message=f"weworkremotely fetch failed category={category}: {type(exc).__name__}",
            level="warning",
        )
        sentry_sdk.capture_exception(exc)
