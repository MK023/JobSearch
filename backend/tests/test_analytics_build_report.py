"""Integration test su ``build_report`` post-refactor PR8.

Copre ognuno dei 10 section builder estratti via un singolo end-to-end call:
- ``build_report(analyses)`` deve produrre markdown con tutti gli heading
  attesi ``## Overview``, ``## Funnel``, ecc.
- Le sezioni si comportano graziose su dataset minimale (1 row).
- Le sezioni con tabelle vuote producono ``_(empty)_`` invece di crash.

L'obiettivo è coprire la coverage SonarCloud sopra 80% sui nuovi helper
senza moltiplicare unit test ridondanti.
"""

from __future__ import annotations

from typing import Any


def _analysis(
    aid: str,
    *,
    company: str = "Acme",
    role: str = "Engineer",
    score: int = 70,
    status: str = "candidato",
    work_mode: str = "remoto",
    location: str = "Italy",
    salary_info: str = "30-40k",
    applied_at: str | None = "2026-01-15T10:00:00+00:00",
) -> dict[str, Any]:
    """Build a minimal analysis dict compatibile col ``extract_features``."""
    return {
        "id": aid,
        "company": company,
        "role": role,
        "score": score,
        "status": status,
        "work_mode": work_mode,
        "location": location,
        "salary_info": salary_info,
        "applied_at": applied_at,
        "interview": {"scheduled_at": "2026-02-01T10:00:00+00:00"} if status == "colloquio" else None,
        "gaps": [],
        "strengths": [],
        "recommendation": "consider",
        "advice": "",
        "tokens_input": 100,
        "tokens_output": 200,
        "cost_usd": 0.01,
        "created_at": "2026-01-10T10:00:00+00:00",
    }


def test_build_report_smoke_with_single_row() -> None:
    """Smoke test: una analisi minimale, build_report non crasha e ritorna markdown."""
    from src.analytics.report import build_report

    out = build_report([_analysis("a1")])

    assert "# JobSearch — Data Analysis Report" in out
    assert "Generated at:" in out
    # All 10 section headers must be present
    assert "## Overview" in out
    assert "## Funnel (by status)" in out
    assert "## Role distribution" in out
    assert "## Score by role bucket" in out
    assert "## Conversion by role" in out
    assert "## Work mode distribution" in out
    assert "## Location bucket distribution" in out
    assert "## Discriminant analysis" in out
    assert "## Numeric differences" in out
    assert "## Score vs outcome (bucketed)" in out
    assert "## Bias signals" in out
    assert "## Top companies" in out


def test_build_report_single_row_no_conflicts_uses_empty_placeholders() -> None:
    """1 row, no kept/rejected mix: bias section emits ``_(nessuno)_`` / ``_(empty)_``."""
    from src.analytics.report import build_report

    out = build_report([_analysis("only", status="candidato", score=70)])
    # Discriminant section: 1 kept, 0 rejected → categorical tables sono empty
    assert "_(empty)_" in out
    # Bias section: same_company conflict assente → placeholder
    assert "_(nessuno)_" in out


def test_build_report_mixed_outcomes_renders_discriminant() -> None:
    """Dataset con kept + rejected attiva la sezione discriminant + bias."""
    from src.analytics.report import build_report

    rows = [
        _analysis("a", status="candidato", score=85),
        _analysis("b", status="colloquio", score=75),
        _analysis("c", status="scartato", score=90),  # high-score rejected
        _analysis("d", status="candidato", score=40),  # low-score kept
        _analysis("e", company="Beta", status="candidato"),
        _analysis("f", company="Beta", status="scartato"),  # same-company conflict
    ]
    out = build_report(rows)
    assert "Kept (candidato/colloquio/offerta)" in out
    assert "High-score rejected" in out
    assert "Low-score kept" in out
    assert "Same company, different outcome" in out
    # The conflict on company "Beta" must appear in the bias section
    assert "Beta" in out or "beta" in out


def test_pct_helper_handles_zero_denominator() -> None:
    """``_pct`` deve ritornare ``0%`` su denom=0 invece di ZeroDivisionError."""
    from src.analytics.report import _pct

    assert _pct(5, 0) == "0%"
    assert _pct(0, 10) == "0.0%"
    assert _pct(3, 4) == "75.0%"
