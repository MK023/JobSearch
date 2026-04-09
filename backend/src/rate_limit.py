"""Rate limiting singleton using slowapi."""

from fastapi import Request
from slowapi import Limiter


def get_client_ip(request: Request) -> str:
    """Extract client IP from trusted proxy header.

    Supports Fly.io (Fly-Client-IP) and Render (X-Forwarded-For).
    Both headers are set by the platform proxy and cannot be spoofed.
    Render strips any client-injected X-Forwarded-For before adding
    the real client IP as the leftmost entry.
    """
    # Fly.io proxy header
    fly_ip = request.headers.get("Fly-Client-IP")
    if fly_ip:
        return fly_ip.strip()
    # Render / standard reverse proxy: leftmost IP in X-Forwarded-For
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    # Local development fallback (no proxy)
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=get_client_ip)
