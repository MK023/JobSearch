"""Unit tests for the bias signal helpers extracted in PR8.

Three independent signals — each tested in isolation to keep regressions
visible on the boundary cases (score thresholds, status sets, conflict
detection).
"""

from __future__ import annotations

from typing import Any

from src.analytics.discriminator import (
    _high_score_rejected_records,
    _low_score_kept_records,
    _same_company_conflicts,
    bias_signals,
)


def _feature(
    fid: str,
    *,
    company: str = "Acme",
    role: str = "Engineer",
    score: int = 70,
    status: str = "candidato",
) -> dict[str, Any]:
    return {"id": fid, "company": company, "role": role, "score": score, "status": status}


class TestHighScoreRejected:
    def test_picks_score_geq_85_in_rejected_status(self) -> None:
        rows = [_feature("a", score=90, status="scartato")]
        assert _high_score_rejected_records(rows) == [
            {"id": "a", "company": "Acme", "role": "Engineer", "score": 90},
        ]

    def test_skips_score_below_85(self) -> None:
        rows = [_feature("a", score=84, status="scartato")]
        assert _high_score_rejected_records(rows) == []

    def test_skips_kept_status(self) -> None:
        rows = [_feature("a", score=99, status="candidato")]
        assert _high_score_rejected_records(rows) == []


class TestLowScoreKept:
    def test_picks_score_below_60_in_kept_status(self) -> None:
        rows = [_feature("a", score=55, status="candidato")]
        assert _low_score_kept_records(rows) == [
            {"id": "a", "company": "Acme", "role": "Engineer", "score": 55},
        ]

    def test_skips_score_geq_60(self) -> None:
        rows = [_feature("a", score=60, status="candidato")]
        assert _low_score_kept_records(rows) == []

    def test_skips_rejected_status(self) -> None:
        rows = [_feature("a", score=30, status="scartato")]
        assert _low_score_kept_records(rows) == []


class TestSameCompanyConflicts:
    def test_detects_kept_vs_rejected_in_same_company(self) -> None:
        rows = [
            _feature("a", company="Acme", status="candidato"),
            _feature("b", company="Acme", status="scartato"),
        ]
        result = _same_company_conflicts(rows)
        assert len(result) == 1
        assert result[0]["company"] == "acme"
        assert len(result[0]["kept"]) == 1
        assert len(result[0]["rejected"]) == 1

    def test_skips_company_with_only_one_outcome(self) -> None:
        rows = [
            _feature("a", company="Acme", status="candidato"),
            _feature("b", company="Acme", status="colloquio"),  # both kept
        ]
        assert _same_company_conflicts(rows) == []

    def test_skips_empty_company(self) -> None:
        rows = [
            _feature("a", company="", status="candidato"),
            _feature("b", company="", status="scartato"),
        ]
        assert _same_company_conflicts(rows) == []


class TestBiasSignalsAggregate:
    def test_combines_three_signals(self) -> None:
        rows = [
            _feature("a", company="Alpha", score=90, status="scartato"),
            _feature("b", company="Gamma", score=40, status="candidato"),
            _feature("c", company="Beta", status="candidato"),
            _feature("d", company="Beta", status="scartato"),
        ]
        result = bias_signals(rows)
        assert {"high_score_rejected", "low_score_kept", "same_company_different_outcome"} == set(result.keys())
        assert len(result["high_score_rejected"]) == 1
        assert len(result["low_score_kept"]) == 1
        assert len(result["same_company_different_outcome"]) == 1
