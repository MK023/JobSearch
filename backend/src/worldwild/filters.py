"""Rule-based pre-filter for WorldWild job offers.

Runs BEFORE the AI analyzer to drop obvious noise cheaply. The blacklist /
whitelist values are tuned on the patterns observed in the Italian market via
Adzuna probe (28 Apr 2026): Help Desk, Junior, Legge 68 protected categories,
sales / marketing roles dominate the volume; the signal is in DevOps, SRE,
Cloud, Platform, Python Engineer, Backend Senior.

These rules WILL produce false negatives (real candidates skipped) — the
trade-off is intentional: cheap drop on volume noise so the AI analyzer
budget is spent on the top-N. False negatives can be recovered later by
loosening rules in PR #5 once the ``decisions`` table has signal.
"""

from __future__ import annotations

import re
from typing import Any

# Hard salary floor: anything advertised below this on a yearly basis is below
# Marco's bucket (sub-junior IT roles). When salary is not advertised we let
# it pass — Adzuna often omits the salary field even on senior postings.
HARD_SALARY_FLOOR_EUR = 25_000

# Title patterns that immediately disqualify an offer.
# Lowercase comparison; word boundaries where ambiguity is high.
_BLACKLIST_TITLE_PATTERNS = [
    r"\bhelp\s*desk\b",
    r"\bhelpdesk\b",
    r"\bjunior\b",
    r"\bstage\b",
    r"\bstagista\b",
    r"\btirocini[oa]\b",  # tirocinio | tirocinia
    r"\btirocinant[ei]\b",
    r"\b(legge|l\.?)\s*68\b",  # categoria protetta
    r"\bcat(\.|egoria)?\s*protett[ao]\b",
    r"\baddett[oa]\b",
    r"\boperai[oa]\b",
    r"\bcommercial[ei]\b",
    r"\bsales\b",
    r"\bmarketing\b",
    r"\b1[°ºo]\s*livello\b",
    r"\b2[°ºo]\s*livello\b",
    r"\bprim[oa]\s*livello\b",
    r"\bsecond[oa]\s*livello\b",
    r"\bapprendista\b",
    r"\b(receptionist|impiegat[oa])\b",
]

# Title patterns that signal a real match for the Cloud/DevOps/Python target.
# At least ONE must match for the offer to pass the whitelist.
_WHITELIST_TITLE_PATTERNS = [
    r"\bdev\s*ops?\b",
    r"\bdevsecops\b",
    r"\bsre\b",
    r"\bsite\s*reliability\b",
    r"\bplatform\s*(engineer|architect)\b",
    r"\bcloud\s*(engineer|architect|specialist)\b",
    r"\bkubernetes\b",
    r"\bk8s\b",
    r"\binfrastruct(?:ure|ur[ae])\b",
    r"\bautomat(?:ion|izzazione)\b",
    r"\bpython\s*(developer|engineer|backend)\b",
    r"\bbackend\s*(developer|engineer|senior)\b",
    r"\bsenior\s*(backend|python|developer)\b",
    r"\bsoftware\s*(architect|engineer\s*senior)\b",
    r"\bml\s*(infrastructure|ops|platform)\b",
    r"\bmlops\b",
    r"\bsecurity\s*(engineer|architect)\b",
    r"\bsystem\s*engineer\b",
    r"\bsistemista\b",  # Italian sysadmin/system engineer
    r"\bobservability\b",
]

# Description hints suggesting remote-first or remote-friendly arrangement.
# Used as a soft signal: an offer that doesn't mention any of these is flagged
# (not auto-rejected) since Italian job boards often omit remote info from
# the title.
_REMOTE_HINTS = [
    "smart working",
    "smartworking",
    "remoto",
    "remote",
    "ibrido",
    "hybrid",
    "telelavoro",
    "lavoro da remoto",
    "work from home",
    "full remote",
    "fully remote",
]

_blacklist_re = [re.compile(p, re.IGNORECASE) for p in _BLACKLIST_TITLE_PATTERNS]
_whitelist_re = [re.compile(p, re.IGNORECASE) for p in _WHITELIST_TITLE_PATTERNS]


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
    for rgx in _blacklist_re:
        if rgx.search(title):
            return False, f"blacklist title: {rgx.pattern}"

    # 2. Whitelist must match (at least one)
    if not any(rgx.search(title) for rgx in _whitelist_re):
        return False, "no whitelist title match"

    # 3. Hard salary floor (only enforced when advertised)
    salary_min = offer.get("salary_min")
    if isinstance(salary_min, int) and salary_min > 0 and salary_min < HARD_SALARY_FLOOR_EUR:
        return False, f"salary_min < {HARD_SALARY_FLOOR_EUR} EUR"

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
    return any(hint in haystack for hint in _REMOTE_HINTS)
