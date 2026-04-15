"""In-app notification center.

Different concept from `src/notifications/` (which handles outbound email
notifications). This package computes the set of in-app alerts the user
should see, derived from existing state (no dedicated DB table).
"""

from .models import Notification, NotificationSeverity, NotificationType
from .service import get_notifications, get_unread_count

__all__ = [
    "Notification",
    "NotificationSeverity",
    "NotificationType",
    "get_notifications",
    "get_unread_count",
]
