"""Rate limiting singleton using slowapi."""

from fastapi import Request
from slowapi import Limiter


def get_client_ip(request: Request) -> str:
    """Extract client IP from trusted proxy header only.

    On Fly.io, Fly-Client-IP is set by the proxy and cannot be spoofed
    by the client. We do NOT trust X-Real-IP or X-Forwarded-For as those
    can be injected by attackers to bypass rate limits.
    """
    fly_ip = request.headers.get("Fly-Client-IP")
    if fly_ip:
        return fly_ip.strip()
    # Local development fallback (no proxy)
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=get_client_ip)
