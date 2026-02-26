"""FastAPI application factory with middleware, routers, and lifespan."""

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from .analysis.routes import router as analysis_router
from .auth.routes import router as auth_router
from .auth.service import ensure_admin_user
from .config import settings
from .cover_letter.routes import router as cover_letter_router
from .cv.routes import router as cv_router
from .dashboard.service import seed_spending_totals
from .database import SessionLocal, get_db
from .dependencies import AuthRequired
from .integrations.cache import create_cache_service
from .pages import router as pages_router
from .rate_limit import limiter

logger = logging.getLogger(__name__)

# Template and static file paths (frontend/ is at project root, sibling of backend/)
_BASE_DIR = Path(__file__).parent.parent.parent
_TEMPLATE_DIR = _BASE_DIR / "frontend" / "templates"
_STATIC_DIR = _BASE_DIR / "frontend" / "static"

_startup_time: float = 0.0


def _run_migrations() -> None:
    """Run Alembic migrations (upgrade head) on startup."""
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config()
    alembic_cfg.set_main_option("script_location", str(Path(__file__).parent.parent / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", settings.effective_database_url)
    command.upgrade(alembic_cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle."""
    global _startup_time
    _startup_time = time.time()

    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY missing. Configure .env file")

    _run_migrations()

    app.state.cache = create_cache_service()

    db = SessionLocal()
    try:
        ensure_admin_user(db)
        seed_spending_totals(db)
        db.commit()

        # Send pending follow-up reminder emails on startup
        from .notifications.service import check_and_send_followup_reminders

        sent = check_and_send_followup_reminders(db)
        if sent:
            db.commit()
    finally:
        db.close()

    yield


def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> Response:
    from fastapi.responses import JSONResponse

    retry_after = "60"
    headers = {"Retry-After": retry_after}

    # Content negotiation: HTML requests get a redirect, API requests get JSON
    accept = request.headers.get("accept", "")
    if "text/html" in accept and "application/json" not in accept:
        return RedirectResponse(url="/", status_code=303, headers=headers)

    return JSONResponse(
        {"error": "Too many requests", "detail": str(exc.detail), "retry_after": int(retry_after)},
        status_code=429,
        headers=headers,
    )


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Job Search Command Center",
        lifespan=lifespan,
    )

    # --- Exception handlers ---
    @app.exception_handler(AuthRequired)
    async def auth_redirect_handler(request: Request, exc: AuthRequired):
        return RedirectResponse(url="/login", status_code=303)

    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            templates = app.state.templates
            return templates.TemplateResponse("404.html", {"request": request}, status_code=404)
        from fastapi.responses import JSONResponse

        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        templates = app.state.templates
        return templates.TemplateResponse("500.html", {"request": request}, status_code=500)

    # --- Middleware stack (LIFO: last added = outermost) ---

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        max_age=86400 * 7,
    )

    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    if settings.trusted_hosts_list != ["*"]:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=settings.trusted_hosts_list,
        )

    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response

    # --- Templates & static files ---
    app.state.templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # --- HTML routers (root level) ---
    # Pages router first so GET / maps to the new dashboard handler
    app.include_router(pages_router)
    app.include_router(auth_router)
    app.include_router(cv_router)
    app.include_router(analysis_router)
    app.include_router(cover_letter_router)

    # --- API v1 (all JSON endpoints) ---
    from .api_v1 import api_v1_router

    app.include_router(api_v1_router)

    # --- Health check ---
    @app.get("/health")
    def health(db: Session = Depends(get_db)):
        db_status = "ok"
        try:
            db.execute(text("SELECT 1"))
        except Exception:
            db_status = "unreachable"

        status = "ok" if db_status == "ok" else "degraded"
        uptime = round(time.time() - _startup_time, 1) if _startup_time else 0.0

        return {
            "status": status,
            "db": db_status,
            "version": "2.0.0",
            "uptime_seconds": uptime,
        }

    return app


app = create_app()
