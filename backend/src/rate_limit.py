"""Rate limiting singleton using slowapi."""

from fastapi import Request
from slowapi import Limiter


def _get_real_ip(request: Request) -> str:
    """Extract client IP, supporting X-Forwarded-For behind nginx proxy."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=_get_real_ip)
