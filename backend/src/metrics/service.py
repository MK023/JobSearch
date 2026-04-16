"""Metrics aggregation service for the admin dashboard."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from .models import RequestMetric

# Auto-cleanup: delete metrics older than this
RETENTION_DAYS = 7


def get_metrics_summary(db: Session) -> dict[str, Any]:
    """Aggregate metrics for the admin dashboard."""
    now = datetime.now(UTC)
    cutoff_24h = now - timedelta(hours=24)

    # Total requests last 24h
    total_24h = db.query(func.count(RequestMetric.id)).filter(RequestMetric.created_at >= cutoff_24h).scalar() or 0

    # Avg latency last 24h
    avg_latency = db.query(func.avg(RequestMetric.duration_ms)).filter(RequestMetric.created_at >= cutoff_24h).scalar()
    avg_latency = round(float(avg_latency), 1) if avg_latency else 0.0

    # P95 latency (approximate via percentile)
    p95_row = (
        db.query(RequestMetric.duration_ms)
        .filter(RequestMetric.created_at >= cutoff_24h)
        .order_by(RequestMetric.duration_ms.desc())
        .offset(max(0, int(total_24h * 0.05)))
        .first()
    )
    p95_latency = round(p95_row[0], 1) if p95_row else 0.0

    # Error rate (4xx + 5xx)
    errors_24h = (
        db.query(func.count(RequestMetric.id))
        .filter(
            RequestMetric.created_at >= cutoff_24h,
            RequestMetric.status_code >= 400,
        )
        .scalar()
        or 0
    )
    error_rate = round(errors_24h / total_24h * 100, 1) if total_24h > 0 else 0.0

    # Top endpoints by request count (last 24h)
    top_endpoints = (
        db.query(
            RequestMetric.endpoint,
            func.count(RequestMetric.id).label("count"),
            func.avg(RequestMetric.duration_ms).label("avg_ms"),
        )
        .filter(RequestMetric.created_at >= cutoff_24h)
        .group_by(RequestMetric.endpoint)
        .order_by(func.count(RequestMetric.id).desc())
        .limit(10)
        .all()
    )

    # Requests per hour (last 24h) for the timeline chart
    hourly = (
        db.query(
            func.date_trunc("hour", RequestMetric.created_at).label("hour"),
            func.count(RequestMetric.id).label("count"),
            func.avg(RequestMetric.duration_ms).label("avg_ms"),
        )
        .filter(RequestMetric.created_at >= cutoff_24h)
        .group_by("hour")
        .order_by("hour")
        .all()
    )

    # Status code breakdown
    status_breakdown = (
        db.query(
            case(
                (RequestMetric.status_code < 300, "2xx"),
                (RequestMetric.status_code < 400, "3xx"),
                (RequestMetric.status_code < 500, "4xx"),
                else_="5xx",
            ).label("group"),
            func.count(RequestMetric.id).label("count"),
        )
        .filter(RequestMetric.created_at >= cutoff_24h)
        .group_by("group")
        .all()
    )

    return {
        "total_24h": total_24h,
        "avg_latency_ms": avg_latency,
        "p95_latency_ms": p95_latency,
        "error_rate": error_rate,
        "errors_24h": errors_24h,
        "top_endpoints": [{"endpoint": e, "count": c, "avg_ms": round(float(a), 1)} for e, c, a in top_endpoints],
        "hourly": [{"hour": h.isoformat(), "count": c, "avg_ms": round(float(a), 1)} for h, c, a in hourly],
        "status_breakdown": {g: c for g, c in status_breakdown},
    }


def cleanup_old_metrics(db: Session) -> int:
    """Delete metrics older than RETENTION_DAYS. Returns count deleted."""
    cutoff = datetime.now(UTC) - timedelta(days=RETENTION_DAYS)
    count = db.query(RequestMetric).filter(RequestMetric.created_at < cutoff).delete()
    db.commit()
    return count
