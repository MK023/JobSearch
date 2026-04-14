"""Persisted key-value preferences for runtime toggles.

Replaces env vars for settings that need to be toggled without redeploy.
Access is whitelisted — see `ALLOWED_KEYS` in service.py.
"""

from .service import ALLOWED_KEYS, get_preference, set_preference

__all__ = ["ALLOWED_KEYS", "get_preference", "set_preference"]
