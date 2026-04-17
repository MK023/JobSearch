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


def bias_signals(features: list[dict[str, Any]]) -> dict[str, Any]:
    """Find pattern suspicious of subjective bias.

    - Rejected high-score (>85) vs kept low-score (<60)
    - Same company, different outcome
    - Same role bucket + similar score, different outcome
    """
    high_score_rejected = [
        {
            "id": f["id"],
            "company": f.get("company"),
            "role": f.get("role"),
            "score": f.get("score"),
        }
        for f in features
        if (f.get("score") or 0) >= 85 and f.get("status") in REJECTED_STATUSES
    ]

    low_score_kept = [
        {
            "id": f["id"],
            "company": f.get("company"),
            "role": f.get("role"),
            "score": f.get("score"),
        }
        for f in features
        if (f.get("score") or 0) < 60 and f.get("status") in KEPT_STATUSES
    ]

    # Same company, different outcome
    by_company: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in features:
        c = (f.get("company") or "").strip().lower()
        if c and f.get("status") in (KEPT_STATUSES | REJECTED_STATUSES):
            by_company[c].append(f)

    conflicting_companies = []
    for company, rows in by_company.items():
        statuses = {r.get("status") for r in rows}
        if statuses & KEPT_STATUSES and statuses & REJECTED_STATUSES:
            conflicting_companies.append(
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
                }
            )

    return {
        "high_score_rejected": high_score_rejected,
        "low_score_kept": low_score_kept,
        "same_company_different_outcome": conflicting_companies,
    }
