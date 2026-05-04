"""Rule-based pre-filter for WorldWild job offers.

Runs BEFORE the AI analyzer to drop obvious noise cheaply. Le regole
(blacklist / whitelist title patterns, remote hints) sono caricate da
``backend/src/worldwild/config/pre_filter_rules.yaml`` con cache singleton —
Marco edita il YAML per cambiare comportamento, niente code push.

Il valore di soglia per il salary floor e' env-driven via ``settings.worldwild_salary_floor_eur``
(default 25k EUR/anno). Override su Render con ``WORLDWILD_SALARY_FLOOR_EUR=<int>``.

Tunato sui sample reali del mercato Adzuna IT (28 apr 2026): Help Desk, Junior,
Legge 68, sales/marketing dominano il rumore; il segnale e' DevOps, SRE, Cloud,
Platform, Python Engineer, Backend Senior. Le regole produrranno false negativi
(candidati reali skipped) — trade-off intenzionale: drop cheap sul rumore di
volume per risparmiare budget AI sul top-N. I falsi negativi si recuperano
dopo allentando le regole nel YAML quando la tabella ``decisions`` ha segnale.
"""

from __future__ import annotations

import functools
import re
from typing import Any

from ..config import settings
from .config import load_pre_filter_rules


@functools.lru_cache(maxsize=1)
def _compiled_blacklist() -> list[re.Pattern[str]]:
    """Pre-compiled blacklist regex (cached). Reset con ``.cache_clear()`` per hot-reload."""
    return [re.compile(p, re.IGNORECASE) for p in load_pre_filter_rules()["blacklist_title_patterns"]]


@functools.lru_cache(maxsize=1)
def _compiled_whitelist() -> list[re.Pattern[str]]:
    """Pre-compiled whitelist regex (cached). Reset con ``.cache_clear()`` per hot-reload."""
    return [re.compile(p, re.IGNORECASE) for p in load_pre_filter_rules()["whitelist_title_patterns"]]


def _remote_hints() -> list[str]:
    """Lista lowercase di sostringhe di hint remoti (rilettura dal cache YAML)."""
    return load_pre_filter_rules()["remote_hints"]


# Backward-compat alias: alcuni test importano direttamente il floor come costante
# top-level. Lo esponiamo come property-like int leggendo settings al import time.
# Per override runtime usa direttamente ``settings.worldwild_salary_floor_eur``.
HARD_SALARY_FLOOR_EUR: int = settings.worldwild_salary_floor_eur


def pre_filter(offer: dict[str, Any]) -> tuple[bool, str]:
    """Apply rule-based pre-filter to a normalized offer dict.

    Returns ``(passed, reason)``:
    - ``(True, "")`` when the offer should proceed to AI analysis / UI.
    - ``(False, <reason>)`` when the offer is rejected; reason fits in the
      ``pre_filter_reason`` column for observability and later rule tuning.
    """
    title = (offer.get("title") or "").strip()
    if not title:
        return False, "empty title"

    # 1. Hard blacklist on title
    for rgx in _compiled_blacklist():
        if rgx.search(title):
            return False, f"blacklist title: {rgx.pattern}"

    # 2. Whitelist must match (at least one)
    if not any(rgx.search(title) for rgx in _compiled_whitelist()):
        return False, "no whitelist title match"

    # 3. Hard salary floor (only enforced when advertised)
    salary_floor = settings.worldwild_salary_floor_eur
    salary_min = offer.get("salary_min")
    if isinstance(salary_min, int) and salary_min > 0 and salary_min < salary_floor:
        return False, f"salary_min < {salary_floor} EUR"

    # 4. Soft remote check on description (warns but doesn't reject)
    # Implementation note: we do NOT reject on this — too many real Italian
    # postings omit the keyword from the description even when remote. The
    # AI analyzer in PR #2 will read description holistically.

    return True, ""


def has_remote_hint(offer: dict[str, Any]) -> bool:
    """Soft signal: does the description / location mention a remote arrangement?

    Used by the UI layer to highlight candidates rather than as a filter gate.
    """
    haystack = " ".join(
        [
            str(offer.get("description") or ""),
            str(offer.get("location") or ""),
            str(offer.get("title") or ""),
        ]
    ).lower()
    return any(hint in haystack for hint in _remote_hints())
