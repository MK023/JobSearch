"""Statistical primitives — distributions, grouping, top categories.

Pure Python (no pandas) so this module stays lightweight and reusable
by future API endpoints that shouldn't pull heavy deps.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def counts_by_status(features: list[dict[str, Any]]) -> dict[str, int]:
    """Count analyses by status (da_valutare, candidato, colloquio, scartato, rifiutato)."""
    return dict(Counter(f.get("status", "unknown") for f in features))


def distribution(features: list[dict[str, Any]], key: str) -> dict[str, int]:
    """Count analyses by any feature key. Skips None values."""
    return dict(Counter(f.get(key) for f in features if f.get(key) is not None))


def top_categories(features: list[dict[str, Any]], key: str, n: int = 10) -> list[tuple[Any, int]]:
    """Top N most frequent values for a feature."""
    return Counter(f.get(key) for f in features if f.get(key) is not None).most_common(n)


def group_stats(features: list[dict[str, Any]], group_by: str, stat_key: str = "score") -> dict[Any, dict[str, float]]:
    """For each group, compute count / mean / min / max of stat_key.

    Example: group_stats(rows, 'role_bucket', 'score') →
        {'devops': {'count': 24, 'mean': 78.2, 'min': 30, 'max': 97}, ...}
    """
    buckets: dict[Any, list[float]] = defaultdict(list)
    for f in features:
        g = f.get(group_by)
        v = f.get(stat_key)
        if g is None or v is None:
            continue
        try:
            buckets[g].append(float(v))
        except (TypeError, ValueError):
            continue

    result: dict[Any, dict[str, float]] = {}
    for g, values in buckets.items():
        if not values:
            continue
        result[g] = {
            "count": float(len(values)),
            "mean": round(sum(values) / len(values), 2),
            "min": min(values),
            "max": max(values),
        }
    return result


def conversion_rate(features: list[dict[str, Any]], group_by: str) -> dict[Any, dict[str, float]]:
    """For each group, compute applied→interview and applied→offer conversion rates.

    Only considers analyses with status in {candidato, colloquio, offerta, rifiutato}.
    Rate is a ratio 0.0-1.0.
    """
    applied_statuses = {"candidato", "colloquio", "offerta", "rifiutato"}
    interview_statuses = {"colloquio", "offerta"}

    buckets: dict[Any, dict[str, int]] = defaultdict(lambda: {"applied": 0, "to_interview": 0, "to_offer": 0})
    for f in features:
        g = f.get(group_by)
        status = f.get("status")
        if g is None or status not in applied_statuses:
            continue
        buckets[g]["applied"] += 1
        if status in interview_statuses or f.get("interview_count", 0) > 0:
            buckets[g]["to_interview"] += 1
        if status == "offerta":
            buckets[g]["to_offer"] += 1

    result: dict[Any, dict[str, float]] = {}
    for g, counts in buckets.items():
        applied = counts["applied"]
        result[g] = {
            "applied": float(applied),
            "to_interview": float(counts["to_interview"]),
            "to_offer": float(counts["to_offer"]),
            "interview_rate": round(counts["to_interview"] / applied, 3) if applied > 0 else 0.0,
            "offer_rate": round(counts["to_offer"] / applied, 3) if applied > 0 else 0.0,
        }
    return result
