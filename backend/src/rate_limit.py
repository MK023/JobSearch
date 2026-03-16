"""Rate limiting singleton using slowapi."""

from fastapi import Request
from slowapi import Limiter


def get_client_ip(request: Request) -> str:
    """Extract client IP using trusted proxy headers (Fly-Client-IP, X-Real-IP)."""
    # Fly.io sets Fly-Client-IP with the real client IP (cannot be spoofed)
    fly_ip = request.headers.get("Fly-Client-IP")
    if fly_ip:
        return fly_ip.strip()
    # Nginx sets X-Real-IP from the direct connection
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=get_client_ip)
