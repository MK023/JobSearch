"""FastAPI application factory with middleware, routers, and lifespan."""

import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from .analysis.routes import router as analysis_router
from .auth.routes import router as auth_router
from .auth.service import ensure_admin_user
from .config import settings
from .cover_letter.routes import router as cover_letter_router
from .cv.routes import router as cv_router
from .dashboard.service import seed_spending_totals
from .database import SessionLocal
from .dependencies import AuthRequired, DbSession
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
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup/shutdown lifecycle."""
    global _startup_time
    _startup_time = time.time()

    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY missing. Configure .env file")

    # Migrations run via fly.toml release_command; run here only for local dev
    if "localhost" in settings.trusted_hosts:
        _run_migrations()

    app.state.cache = create_cache_service()

    db = SessionLocal()
    try:
        ensure_admin_user(db)
        seed_spending_totals(db)
        db.commit()
    finally:
        db.close()

    yield


def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """Return HTML redirect or JSON error depending on Accept header."""
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
    async def auth_redirect_handler(request: Request, exc: AuthRequired) -> Response:
        """Redirect unauthenticated users to the login page."""
        return RedirectResponse(url="/login", status_code=303)

    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)  # type: ignore[arg-type]

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
        """Render custom 404 page or return JSON for other HTTP errors."""
        if exc.status_code == 404:
            templates = app.state.templates
            return templates.TemplateResponse(request, "404.html", status_code=404)  # type: ignore[no-any-return]
        from fastapi.responses import JSONResponse

        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> Response:
        """Log unhandled exceptions and render a 500 error page."""
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        templates = app.state.templates
        return templates.TemplateResponse(request, "500.html", status_code=500)  # type: ignore[no-any-return]

    # --- Middleware stack (LIFO: last added = outermost) ---
    # Order matters: first added = innermost, last added = outermost.
    # Request flow: CORS → TrustedHost → SecurityHeaders → SlowAPI → Session → App

    _is_production = "localhost" not in settings.trusted_hosts
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        max_age=86400 * 2,
        https_only=_is_production,
        same_site="lax",
    )

    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Response:
        """Add security headers (CSP, HSTS, X-Frame-Options, etc.) to all responses."""
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self' https://*.r2.cloudflarestorage.com https://api.open-meteo.com; "
            "frame-ancestors 'none'"
        )
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response

    if settings.trusted_hosts_list != ["*"]:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=settings.trusted_hosts_list,
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
    )

    # --- Templates & static files ---
    app.state.templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))
    # Auto cache-bust: short git commit hash, fallback to timestamp
    import subprocess as _sp

    try:
        _asset_v = _sp.check_output(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            text=True,
            stderr=_sp.DEVNULL,
        ).strip()
    except Exception:
        _asset_v = str(int(time.time()))
    app.state.templates.env.globals["asset_v"] = _asset_v
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
    def health(db: DbSession) -> dict[str, Any]:
        """Return application health status including DB connectivity and uptime."""
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
