"""FastAPI application factory with middleware, routers, and lifespan."""

import logging
import os as _os
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
from sqlalchemy import select, text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from .analysis.routes import router as analysis_router
from .auth.routes import router as auth_router
from .auth.service import ensure_admin_user
from .config import settings

# Sentry — initialize before app creation so FastAPI integration auto-activates
# Skip Sentry during pytest runs — otherwise test-induced errors (mocked
# R2 failures, broken PDFs, etc.) pollute the production dashboard with
# alerts from the developer's local machine.
_is_pytest = _os.environ.get("PYTEST_CURRENT_TEST") or "pytest" in _os.environ.get("_", "")

if settings.sentry_dsn and not _is_pytest:
    import logging as _logging

    import sentry_sdk
    from sentry_sdk.integrations.logging import LoggingIntegration

    _integrations: list = [
        # Capture WARNING+ as Sentry events (INFO+ as breadcrumbs)
        LoggingIntegration(level=_logging.INFO, event_level=_logging.WARNING),
    ]
    try:
        from sentry_sdk.integrations.mcp import MCPIntegration

        _integrations.append(MCPIntegration())
    except Exception:  # noqa: S110 — DidNotEnable if mcp package missing
        pass

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        send_default_pii=True,
        traces_sample_rate=1.0,  # 14-day trial: capture everything
        profiles_sample_rate=1.0,  # transaction-based profiling
        profile_session_sample_rate=1.0,  # continuous profiling
        profile_lifecycle="trace",
        release="jobsearch@1.0.0",
        environment="production" if _os.environ.get("RENDER") else "development",
        auto_session_tracking=True,
        enable_logs=True,
        integrations=_integrations,
    )
from .analytics_page.routes import page_router as analytics_page_router  # noqa: E402
from .cover_letter.routes import router as cover_letter_router  # noqa: E402
from .cv.routes import router as cv_router  # noqa: E402
from .dashboard.service import seed_spending_totals  # noqa: E402
from .database import SessionLocal  # noqa: E402
from .dependencies import AuthRequired, DbSession  # noqa: E402
from .integrations.cache import create_cache_service  # noqa: E402
from .pages import router as pages_router  # noqa: E402
from .preferences.routes import router as preferences_router  # noqa: E402
from .rate_limit import limiter  # noqa: E402

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

    # Run migrations on startup (safe: alembic upgrade head is idempotent)
    _run_migrations()

    app.state.cache = create_cache_service()

    from .batch.service import cleanup_stale_running

    db = SessionLocal()
    try:
        ensure_admin_user(db)
        seed_spending_totals(db)
        # Recover batch items left RUNNING by a prior crash/deploy (SIGTERM
        # kills background tasks without a chance to mark items failed).
        cleanup_stale_running(db)
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
        max_age=14400,  # 4 hours (was 48h — too long for exposed app)
        https_only=_is_production,
        same_site="strict",  # Blocks cross-site requests entirely (CSRF protection)
    )

    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    @app.middleware("http")
    async def csrf_origin_check(request: Request, call_next: Any) -> Response:
        """Block cross-origin state-changing requests (CSRF protection).

        Validates Origin header on POST/PUT/DELETE against trusted hosts.
        Combined with SameSite=strict cookies, this provides robust CSRF defense.
        """
        if request.method in ("POST", "PUT", "DELETE"):
            origin = request.headers.get("origin")
            # API key requests (MCP server) are exempt — no browser session
            has_api_key = bool(request.headers.get("x-api-key"))
            if origin and not has_api_key:
                from urllib.parse import urlparse

                origin_host = urlparse(origin).hostname or ""
                allowed = settings.trusted_hosts_list + ["localhost", "127.0.0.1"]
                if origin_host not in allowed:
                    from fastapi.responses import JSONResponse

                    return JSONResponse(
                        {"error": "Cross-origin request blocked"},
                        status_code=403,
                    )
        response: Response = await call_next(request)
        return response

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Response:
        """Add security headers (CSP, HSTS, X-Frame-Options, etc.) to all responses."""
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://unpkg.com https://js-de.sentry-cdn.com https://browser.sentry-cdn.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https://*.r2.cloudflarestorage.com https://api.open-meteo.com https://*.sentry.io; "
            "frame-ancestors 'none'"
        )
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
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
        allow_headers=["Content-Type", "Authorization", "X-Requested-With", "X-API-Key"],
    )

    from .metrics.middleware import MetricsMiddleware

    app.add_middleware(MetricsMiddleware)

    # --- Templates & static files ---
    app.state.templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))
    # Auto cache-bust: short git commit hash, fallback to timestamp
    import subprocess as _sp

    try:
        _asset_v = _sp.check_output(  # noqa: S603
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            text=True,
            stderr=_sp.DEVNULL,
        ).strip()
    except Exception:
        _asset_v = str(int(time.time()))
    app.state.templates.env.globals["asset_v"] = _asset_v

    # Timezone-aware "now" helper for templates — used by interview_detail.html
    # to decide whether a round is past (scheduled_at < now) or future.
    from datetime import UTC as _UTC
    from datetime import datetime as _datetime

    app.state.templates.env.globals["now"] = lambda: _datetime.now(_UTC)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # --- HTML routers (root level) ---
    # Pages router first so GET / maps to the new dashboard handler
    app.include_router(pages_router)
    app.include_router(analytics_page_router)
    app.include_router(auth_router)
    app.include_router(cv_router)
    app.include_router(analysis_router)
    app.include_router(cover_letter_router)
    app.include_router(preferences_router)

    # --- API v1 (all JSON endpoints) ---
    from .api_v1 import api_v1_router

    app.include_router(api_v1_router)

    # --- Favicon (browsers request /favicon.ico by default; redirect to SVG) ---
    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        """Serve the SVG favicon for browsers requesting /favicon.ico directly."""
        from fastapi.responses import FileResponse

        return FileResponse(_STATIC_DIR / "favicon.svg", media_type="image/svg+xml")

    # --- Health check ---
    @app.get("/health")
    def health(request: Request, db: DbSession) -> dict[str, Any]:
        """Return application health status.

        Unauthenticated requests get a minimal response (for Render health checks).
        Authenticated requests get full diagnostics.
        """
        db_status = "ok"
        try:
            db.execute(select(1))
        except Exception:
            db_status = "unreachable"

        status = "ok" if db_status == "ok" else "degraded"

        # Minimal response for unauthenticated health probes
        if not request.session.get("user_id"):
            return {"status": status}

        # Full diagnostics for authenticated admin
        uptime = round(time.time() - _startup_time, 1) if _startup_time else 0.0

        import contextlib

        cache_stats: dict[str, int] = {}
        with contextlib.suppress(Exception):
            cache_stats = app.state.cache.stats()

        db_size_mb: float | None = None
        with contextlib.suppress(Exception):
            size_bytes = db.execute(text("SELECT pg_database_size(current_database())")).scalar()
            if size_bytes is not None:
                db_size_mb = round(int(size_bytes) / 1024 / 1024, 2)

        return {
            "status": status,
            "db": db_status,
            "db_size_mb": db_size_mb,
            "version": "2.0.0",
            "uptime_seconds": uptime,
            "cache": cache_stats,
        }

    # --- Dedicated DB health check for Checkly ---
    @app.get("/health/db")
    def health_db(db: DbSession) -> dict[str, Any]:
        """Lightweight DB-only health check for external monitoring (Checkly).

        Returns 200 if DB is reachable, 503 if not. No auth required — this
        endpoint reveals no sensitive info, just connectivity status.
        """
        try:
            db.execute(select(1))
            return {"status": "ok", "db": "connected"}
        except Exception:
            from fastapi.responses import JSONResponse

            return JSONResponse({"status": "error", "db": "unreachable"}, status_code=503)  # type: ignore[return-value]

    # --- Dedicated cache health check for Checkly ---
    @app.get("/health/cache")
    def health_cache() -> dict[str, Any]:
        """Cache-only health check for external monitoring."""
        import contextlib

        cache_status = "ok"
        with contextlib.suppress(Exception):
            stats = app.state.cache.stats()
            if not isinstance(stats, dict):
                cache_status = "degraded"
        return {"status": cache_status}

    return app


app = create_app()
