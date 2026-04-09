"""Rate limiting singleton using slowapi."""

from fastapi import Request
from slowapi import Limiter


def get_client_ip(request: Request) -> str:
    """Extract client IP from trusted proxy header.

    Render sets X-Forwarded-For with the real client IP as the
    leftmost entry, stripping any client-injected values.
    """
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    # Local development fallback (no proxy)
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=get_client_ip)
