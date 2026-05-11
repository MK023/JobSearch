"""Helper condivisi tra gli adapter di ingest WorldWild.

Estratto cipolla PR4: i 9 adapter sotto ``integrations/`` (adzuna, arbeitnow,
findwork, jobicy, remoteok, remotive, themuse, weworkremotely, workingnomads)
duplicavano lo stesso codice triviale per:

- normalizzazione stringa (clip + strip + None-safe)
- parsing datetime ISO con suffisso ``Z`` → tz-aware UTC
- breadcrumb Sentry difensivo per errori graceful

Tre soli helper, signature minimale, zero dipendenze esterne. Behavior-preserving:
ogni helper riproduce alla lettera il pattern originale degli adapter.

Fuori scope: dedup cross-page (state mutabile sull'iterazione, non si presta a
una signature pulita) e wrapper httpx (auth/headers/params troppo eterogenei
per giustificare un'astrazione).
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import Any


def safe_str(value: Any, max_len: int) -> str:
    """Coerce ``value`` to stripped string, clipped a ``max_len`` caratteri.

    Restituisce stringa vuota quando ``value`` è ``None``: gli adapter
    upstream preferiscono campi vuoti a ``None`` per il loro shape canonico.
    """
    if value is None:
        return ""
    return str(value).strip()[:max_len]


def parse_iso_datetime(value: Any) -> datetime | None:
    """Parsa una ISO 8601 string in ``datetime`` tz-aware UTC.

    Accetta sia il suffisso ``Z`` (Adzuna, Findwork, RemoteOK, …) sia gli
    offset espliciti (``+00:00``). Quando l'input è privo di tzinfo applica
    UTC: tutti gli adapter trattano queste date come istanti assoluti, mai
    locali.

    Restituisce ``None`` su input vuoto, malformato, o di tipo non parsabile —
    il caller persiste ``None`` nel campo ``posted_at`` senza rumore.
    """
    if not value:
        return None
    try:
        normalized = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def record_error(exc: Exception, *, source: str, **context: Any) -> None:
    """Aggiunge un breadcrumb Sentry per un errore graceful di adapter.

    Mai rilancia: Sentry non è inizializzato in test/local dev e non vogliamo
    che il fallimento di logging rimbalzi sul caller. ``contextlib.suppress``
    esprime in modo Pythonico l'intento "ingoia intenzionalmente".

    Solo breadcrumb (no ``capture_exception``): gli errori upstream sono già
    gestiti graceful con ``return []`` dal caller. Niente issue spam su Sentry
    per servizio vendor degraded.

    ``context`` opzionale viene serializzato nel message come ``key=value``
    (separato da spazi) preservando i tre formati storici degli adapter:
    nessun kwarg, ``page=N``, ``category=X``.
    """
    with contextlib.suppress(Exception):
        import sentry_sdk  # type: ignore[import-not-found]  # pyright: ignore[reportMissingImports]

        ctx_str = " ".join(f"{k}={v}" for k, v in context.items())
        suffix = f" {ctx_str}" if ctx_str else ""
        sentry_sdk.add_breadcrumb(
            category=source,
            message=f"{source} fetch failed{suffix}: {type(exc).__name__}",
            level="warning",
        )
