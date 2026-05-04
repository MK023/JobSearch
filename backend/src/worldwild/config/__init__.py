"""Config loader for Worldwild — YAML-driven runtime rules + queries.

Centralizza il caricamento dei file YAML che governano il pre-filter e le query
per source. Pattern: cache singleton via ``functools.lru_cache(maxsize=1)`` —
il file viene letto una sola volta per processo. Per forzare hot-reload (es. dopo
una modifica live al YAML) chiamare ``load_pre_filter_rules.cache_clear()`` o
``load_queries_config.cache_clear()``.

Failure mode: se il YAML manca o e' malformato, ritorniamo una struttura vuota
"safe" — il pre_filter degrada a "lascia passare tutto" / "blocca tutto in base
a logica chiamante", invece di crashare l'ingest. La cron loggia (via Sentry) la
mancanza tramite errore upstream se le liste sono vuote inattese.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

_CONFIG_DIR = Path(__file__).parent


@functools.lru_cache(maxsize=1)
def load_pre_filter_rules() -> dict[str, list[str]]:
    """Carica le regole di pre-filter dal file ``pre_filter_rules.yaml`` (cached).

    Returns:
        Dict con chiavi ``blacklist_title_patterns``, ``whitelist_title_patterns``,
        ``remote_hints``. Se il YAML e' assente o malformato ritorna liste vuote
        (mai ``KeyError`` per i caller).
    """
    path = _CONFIG_DIR / "pre_filter_rules.yaml"
    if not path.exists():
        return {
            "blacklist_title_patterns": [],
            "whitelist_title_patterns": [],
            "remote_hints": [],
        }
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {
        "blacklist_title_patterns": list(data.get("blacklist_title_patterns") or []),
        "whitelist_title_patterns": list(data.get("whitelist_title_patterns") or []),
        "remote_hints": list(data.get("remote_hints") or []),
    }


@functools.lru_cache(maxsize=1)
def load_queries_config() -> dict[str, dict[str, Any]]:
    """Carica la config per-source dal file ``queries.yaml`` (cached).

    Returns:
        Dict ``{source_name: {default_queries: [...], ...}}``. Dict vuoto se il
        YAML manca o e' malformato. I caller dovrebbero usare ``.get(source, {})``
        + default sensato per non rompere quando un source non e' ancora wired.
    """
    path = _CONFIG_DIR / "queries.yaml"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


__all__ = ["load_pre_filter_rules", "load_queries_config"]
