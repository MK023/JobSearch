"""Lightweight request metrics middleware.

Records endpoint, method, status code, and duration for every request
except health checks and static files. Writes directly to DB via a
background task to avoid slowing down the response.
"""

import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from ..database import SessionLocal
from .models import RequestMetric

# Paths to skip — high-frequency, low-value for metrics
_SKIP_PREFIXES = ("/health", "/static/", "/favicon")


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record request duration and status to the request_metrics table."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        # Skip noisy endpoints
        if any(path.startswith(p) for p in _SKIP_PREFIXES):
            return await call_next(request)

        start = time.perf_counter()
        status_code = 500  # default if handler throws
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            self._record(path, request.method, status_code, duration_ms)
            raise

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        self._record(path, request.method, status_code, duration_ms)
        return response

    @staticmethod
    def _record(endpoint: str, method: str, status_code: int, duration_ms: float) -> None:
        """Fire-and-forget DB write (sync, separate session)."""
        try:
            db = SessionLocal()
            try:
                db.add(
                    RequestMetric(
                        endpoint=endpoint[:200],
                        method=method,
                        status_code=status_code,
                        duration_ms=duration_ms,
                    )
                )
                db.commit()
            finally:
                db.close()
        except Exception:  # noqa: S110 — telemetry must never break requests
            pass
