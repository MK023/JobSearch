"""API v1 router: all JSON endpoints under /api/v1 prefix."""

from fastapi import APIRouter

from .analysis.api_routes import router as analysis_api_router
from .analysis.followup_routes import router as followup_router
from .batch.routes import router as batch_router
from .contacts.routes import router as contacts_router
from .dashboard.routes import router as dashboard_router

api_v1_router = APIRouter(prefix="/api/v1", tags=["api-v1"])

api_v1_router.include_router(analysis_api_router)
api_v1_router.include_router(followup_router)
api_v1_router.include_router(contacts_router)
api_v1_router.include_router(dashboard_router)
api_v1_router.include_router(batch_router)
