"""API v1 router: all JSON endpoints under /api/v1 prefix."""

from fastapi import APIRouter

from .agenda.routes import router as agenda_router
from .analysis.api_routes import router as analysis_api_router
from .analysis.followup_routes import router as followup_router
from .analytics_page.routes import api_router as analytics_api_router
from .batch.routes import router as batch_router
from .contacts.routes import router as contacts_router
from .dashboard.routes import router as dashboard_router
from .inbox.routes import router as inbox_router
from .interview.file_routes import router as file_router
from .interview.routes import router as interview_router
from .notification_center.routes import router as notification_router
from .read_routes import router as read_router

api_v1_router = APIRouter(prefix="/api/v1", tags=["api-v1"])

api_v1_router.include_router(read_router)
api_v1_router.include_router(analysis_api_router)
api_v1_router.include_router(followup_router)
api_v1_router.include_router(contacts_router)
api_v1_router.include_router(dashboard_router)
api_v1_router.include_router(batch_router)
api_v1_router.include_router(inbox_router)
api_v1_router.include_router(interview_router)
api_v1_router.include_router(file_router)
api_v1_router.include_router(notification_router)
api_v1_router.include_router(agenda_router)
api_v1_router.include_router(analytics_api_router)
