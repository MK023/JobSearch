"""UI badges helpers — funzioni pure di derivazione semantica per le card.

Estratte qui per essere riusate via filter Jinja2 nei partial di template
(``_analysis_badges.html``, ``analysis_detail.html``). Mantengono la
separation of concerns: il template chiama ``salary | salary_bracket(is_freelance)``
e ``track | career_track_label`` senza ricalcolare logica in n posti.
"""

from __future__ import annotations

import re
from typing import Final

# ── Career track ──────────────────────────────────────────────────────

_TRACK_LABELS: Final[dict[str, tuple[str, str, str]]] = {
    # enum_value: (icon, label, css_modifier)
    "plan_a_devops": ("🛠", "DevOps", "track-primary"),
    "hybrid_a_b": ("🔀", "Hybrid", "track-primary"),
    "plan_b_dev": ("💻", "Dev", "track-secondary"),
    "cybersec_junior_ok": ("🛡", "Cybersec", "track-secondary"),
    "out_of_scope": ("⚫", "Off-target", "track-off"),
}


def career_track_label(track: str) -> dict[str, str]:
    """Map enum ``career_track`` (vedi ``AnalysisAIResponse.career_track``) a label friendly.

    Default ``track-primary`` su valori sconosciuti per non perdere
    info utile su row legacy con enum non più mappato.
    """
    icon, label, css = _TRACK_LABELS.get(track or "", ("🔀", "Hybrid", "track-primary"))
    return {"icon": icon, "label": label, "css": css}


# ── Salary bracket ────────────────────────────────────────────────────

# Tipiche soglie target Marco mid (memo `feedback_salary_range_not_secco_number`):
#   - dipendente: ≥45k = high, 35-45k = mid, <35k = low
#   - freelance:  ≥260€/d = high, <260€/d = low (BAFNA Capgemini/Hays)
_RAL_HIGH_THRESHOLD = 45_000
_RAL_MID_THRESHOLD = 35_000
_DAILY_RATE_THRESHOLD = 260


# Numero accettando varianti italiane:
#   "45.000 €", "45000€", "€45k", "45 mila", "EUR 45.000", "45-55k RAL"
# Cerca il PRIMO valore numerico con possibile separatore migliaia.
_NUMBER_RE = re.compile(r"(\d[\d.,]*)\s*(k|mila)?", flags=re.IGNORECASE)


def _parse_first_amount(text: str) -> int | None:
    """Estrai il primo numero ragionevole come intero (in euro)."""
    m = _NUMBER_RE.search(text)
    if not m:
        return None
    raw = m.group(1).replace(".", "").replace(",", "")
    try:
        value = int(raw)
    except ValueError:
        return None
    suffix = (m.group(2) or "").lower()
    if suffix in ("k", "mila"):
        return value * 1000
    # Se il numero è piccolo (<1000) e non c'è suffisso, probabilmente è
    # un day-rate o un mensile. Non moltiplichiamo: il caller distingue.
    return value


def salary_bracket(salary_info: str | None, is_freelance: bool = False) -> dict[str, str]:
    """Classifica il salary del JD in bracket high/mid/low/unknown.

    Output dict pronto per template: ``{"bracket": str, "label": str, "css": str}``.

    Bracket per dipendente:
        ≥45k → ``high``      (verde) — target Marco mid
        35-45k → ``mid``    (giallo) — sotto-target ma valutabile
        <35k → ``low``      (rosso) — sotto-prezzo
        vuoto/non-parsable → ``unknown`` (muted) — segnale red flag implicito

    Bracket per freelance (rate giornaliero):
        ≥260€/d → ``high``  (verde) — al pari BAFNA Hays/Capgemini Marco
        <260€/d → ``low``   (rosso) — sotto-prezzo body rental
        vuoto → ``unknown`` (muted)
    """
    if not salary_info or not salary_info.strip():
        return {"bracket": "unknown", "label": "💰 ?", "css": "salary-unknown"}

    amount = _parse_first_amount(salary_info)
    if amount is None:
        return {"bracket": "unknown", "label": "💰 ?", "css": "salary-unknown"}

    if is_freelance:
        if amount >= _DAILY_RATE_THRESHOLD:
            return {"bracket": "high", "label": f"💰 ≥{_DAILY_RATE_THRESHOLD}€/d", "css": "salary-high"}
        return {"bracket": "low", "label": f"💰 <{_DAILY_RATE_THRESHOLD}€/d", "css": "salary-low"}

    # Dipendente: euristica RAL annuale
    if amount >= _RAL_HIGH_THRESHOLD:
        return {"bracket": "high", "label": f"💰 ≥{_RAL_HIGH_THRESHOLD // 1000}k", "css": "salary-high"}
    if amount >= _RAL_MID_THRESHOLD:
        return {
            "bracket": "mid",
            "label": f"💰 {_RAL_MID_THRESHOLD // 1000}-{_RAL_HIGH_THRESHOLD // 1000}k",
            "css": "salary-mid",
        }
    return {"bracket": "low", "label": f"💰 <{_RAL_MID_THRESHOLD // 1000}k", "css": "salary-low"}


# ── Recommendation ────────────────────────────────────────────────────

_REC_LABELS: Final[dict[str, tuple[str, str, str]]] = {
    "APPLY": ("🚀", "APPLY", "rec-apply"),
    "CONSIDER": ("🤔", "CONSIDER", "rec-consider"),
    "SKIP": ("⏭", "SKIP", "rec-skip"),
}


def recommendation_badge(rec: str) -> dict[str, str]:
    """Map ``recommendation`` AI a icon + label + css class."""
    icon, label, css = _REC_LABELS.get((rec or "").upper(), ("🤔", "CONSIDER", "rec-consider"))
    return {"icon": icon, "label": label, "css": css}
