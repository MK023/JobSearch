"""FastAPI application factory with middleware, routers, and lifespan."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from .analysis.routes import router as analysis_router
from .auth.models import User
from .auth.routes import router as auth_router
from .auth.service import ensure_admin_user
from .config import settings
from .cover_letter.routes import router as cover_letter_router
from .cv.routes import router as cv_router
from .dashboard.service import seed_spending_totals
from .database import SessionLocal, get_db
from .dependencies import AuthRequired, get_current_user
from .integrations.cache import create_cache_service
from .rate_limit import limiter

# Template and static file paths (frontend/ is at project root, sibling of backend/)
_BASE_DIR = Path(__file__).parent.parent.parent
_TEMPLATE_DIR = _BASE_DIR / "frontend" / "templates"
_STATIC_DIR = _BASE_DIR / "frontend" / "static"


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
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY missing. Configure .env file")

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
    from fastapi.responses import JSONResponse

    return JSONResponse(
        {"error": "Too many requests", "detail": str(exc.detail)},
        status_code=429,
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

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains"
            )
        return response

    # --- Templates & static files ---
    app.state.templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # --- Root route ---
    @app.get("/", response_class=HTMLResponse)
    def home(
        request: Request,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ):
        from .analysis.routes import _render_page

        return _render_page(request, db, user)

    # --- HTML routers (root level) ---
    app.include_router(auth_router)
    app.include_router(cv_router)
    app.include_router(analysis_router)
    app.include_router(cover_letter_router)

    # --- API v1 (all JSON endpoints) ---
    from .api_v1 import api_v1_router

    app.include_router(api_v1_router)

    # --- Health check ---
    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
