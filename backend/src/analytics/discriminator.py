"""Discriminant analysis — what distinguishes kept from rejected candidatures.

Finds features that differ most between two groups (e.g. scartato vs candidato),
and detects bias patterns (same score / same company / different outcome).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

KEPT_STATUSES = {"candidato", "colloquio", "offerta"}
REJECTED_STATUSES = {"scartato"}  # "rifiutato" = rejected BY company, not by user


def _split_groups(features: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split features into (kept, rejected) based on status."""
    kept = [f for f in features if f.get("status") in KEPT_STATUSES]
    rejected = [f for f in features if f.get("status") in REJECTED_STATUSES]
    return kept, rejected


def _categorical_lift(kept: list[dict[str, Any]], rejected: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    """For each value of `key`, compute frequency in kept vs rejected and log-ratio.

    High positive lift → characteristic of kept. Negative → characteristic of rejected.
    """
    if not kept or not rejected:
        return []

    kept_counts = Counter(f.get(key) for f in kept if f.get(key) is not None)
    rej_counts = Counter(f.get(key) for f in rejected if f.get(key) is not None)
    total_kept = sum(kept_counts.values()) or 1
    total_rej = sum(rej_counts.values()) or 1

    all_values = set(kept_counts) | set(rej_counts)
    rows = []
    for v in all_values:
        k_freq = kept_counts.get(v, 0) / total_kept
        r_freq = rej_counts.get(v, 0) / total_rej
        # Laplace smoothing to avoid div-by-zero
        lift = round((k_freq + 0.01) / (r_freq + 0.01), 2)
        rows.append(
            {
                "value": v,
                "kept_count": kept_counts.get(v, 0),
                "rejected_count": rej_counts.get(v, 0),
                "kept_pct": round(k_freq * 100, 1),
                "rejected_pct": round(r_freq * 100, 1),
                "lift": lift,  # >1 means more common in kept
            }
        )
    rows.sort(key=lambda r: float(r["lift"] or 0), reverse=True)
    return rows


def _numeric_delta(kept: list[dict[str, Any]], rejected: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    """Mean/median comparison for a numeric feature."""
    kv = [f[key] for f in kept if isinstance(f.get(key), int | float) and f.get(key) is not None]
    rv = [f[key] for f in rejected if isinstance(f.get(key), int | float) and f.get(key) is not None]
    if not kv or not rv:
        return None
    kv_mean = sum(kv) / len(kv)
    rv_mean = sum(rv) / len(rv)
    return {
        "kept_mean": round(kv_mean, 2),
        "rejected_mean": round(rv_mean, 2),
        "delta": round(kv_mean - rv_mean, 2),
        "kept_n": len(kv),
        "rejected_n": len(rv),
    }


def discriminant_features(features: list[dict[str, Any]]) -> dict[str, Any]:
    """Full discriminant report: categorical lifts + numeric deltas."""
    kept, rejected = _split_groups(features)

    categorical_keys = [
        "role_bucket",
        "location_bucket",
        "work_mode",
        "is_piva",
        "is_body_rental",
        "is_recruiter",
        "experience_level",
        "recommendation",
    ]
    numeric_keys = ["score", "salary_midpoint_k", "years_required", "gaps_blocking", "gaps_count"]

    return {
        "kept_total": len(kept),
        "rejected_total": len(rejected),
        "categorical": {key: _categorical_lift(kept, rejected, key) for key in categorical_keys},
        "numeric": {key: _numeric_delta(kept, rejected, key) for key in numeric_keys},
    }


def score_vs_outcome(features: list[dict[str, Any]]) -> dict[str, Any]:
    """Bucket by score range and show outcome distribution per bucket.

    Useful to detect bias: low-score kept or high-score rejected.
    """
    buckets = [
        (0, 40, "<40"),
        (40, 60, "40-59"),
        (60, 75, "60-74"),
        (75, 85, "75-84"),
        (85, 101, "85+"),
    ]
    result: dict[str, dict[str, int]] = {label: defaultdict(int) for _, _, label in buckets}  # type: ignore[misc]

    for f in features:
        score = f.get("score") or 0
        status = f.get("status") or "unknown"
        for low, high, label in buckets:
            if low <= score < high:
                result[label][status] += 1
                break

    return {label: dict(counts) for label, counts in result.items()}


def _summary_row(f: dict[str, Any]) -> dict[str, Any]:
    """Compact identity for a feature row in a bias report."""
    return {
        "id": f["id"],
        "company": f.get("company"),
        "role": f.get("role"),
        "score": f.get("score"),
    }


def _high_score_rejected_records(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Features con score ≥ 85 ma scartati — possibili rifiuti soggettivi."""
    return [_summary_row(f) for f in features if (f.get("score") or 0) >= 85 and f.get("status") in REJECTED_STATUSES]


def _low_score_kept_records(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Features con score < 60 ma kept — possibili candidature emotive."""
    return [_summary_row(f) for f in features if (f.get("score") or 0) < 60 and f.get("status") in KEPT_STATUSES]


def _same_company_conflicts(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aziende su cui esistono sia ruoli kept che ruoli rejected.

    Segnale di bias se due offerte simili dalla stessa azienda hanno avuto
    esiti opposti — la decisione probabilmente è dipesa da fattori esterni
    al merito (ruolo specifico, mood, contesto).
    """
    by_company: dict[str, list[dict[str, Any]]] = defaultdict(list)
    relevant_statuses = KEPT_STATUSES | REJECTED_STATUSES
    for f in features:
        company = (f.get("company") or "").strip().lower()
        if company and f.get("status") in relevant_statuses:
            by_company[company].append(f)

    conflicts: list[dict[str, Any]] = []
    for company, rows in by_company.items():
        statuses = {r.get("status") for r in rows}
        if not (statuses & KEPT_STATUSES and statuses & REJECTED_STATUSES):
            continue
        conflicts.append(
            {
                "company": company,
                "kept": [
                    {"id": r["id"], "role": r.get("role"), "score": r.get("score")}
                    for r in rows
                    if r.get("status") in KEPT_STATUSES
                ],
                "rejected": [
                    {"id": r["id"], "role": r.get("role"), "score": r.get("score")}
                    for r in rows
                    if r.get("status") in REJECTED_STATUSES
                ],
            },
        )
    return conflicts


def bias_signals(features: list[dict[str, Any]]) -> dict[str, Any]:
    """Find patterns suspicious of subjective bias.

    Three independent signals aggregated in a single dict for the report:
    - high-score rejected (≥85 ma scartati)
    - low-score kept (<60 ma candidato/colloquio/offerta)
    - same company with opposite outcomes
    """
    return {
        "high_score_rejected": _high_score_rejected_records(features),
        "low_score_kept": _low_score_kept_records(features),
        "same_company_different_outcome": _same_company_conflicts(features),
    }
