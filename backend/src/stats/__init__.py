"""Stats page — pure SQL aggregates over job_analyses.

No Pandas, no Polars: the DB is small and aggregations are simple,
so raw SQL keeps us closest to the source of truth and imposes no new
dependencies.
"""

from .service import get_stats

__all__ = ["get_stats"]
