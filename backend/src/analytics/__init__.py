"""Analytics module — data-science primitives for analyzing the candidature DB.

Reusable building blocks: feature extraction, discriminant analysis,
bias detection, report generation. Used by scripts/analyze_db.py today
and by a future POST /api/v1/admin/run-analytics endpoint.

The functions here are pure (no DB, no HTTP) — they operate on a list
of analysis dicts as exported by /api/v1/admin/export/analyses.
"""

from .discriminator import discriminant_features, score_vs_outcome
from .extractor import extract_features, feature_summary
from .report import build_report
from .stats import (
    counts_by_status,
    distribution,
    group_stats,
    top_categories,
)

__all__ = [
    "build_report",
    "counts_by_status",
    "discriminant_features",
    "distribution",
    "extract_features",
    "feature_summary",
    "group_stats",
    "score_vs_outcome",
    "top_categories",
]
