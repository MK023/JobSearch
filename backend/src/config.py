"""Application configuration via environment variables."""

import os as _os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    # Safe default: local SQLite file (no credentials embedded in source).
    # Production deploys (Render, Docker, CI) override via DATABASE_URL env var.
    database_url: str = "sqlite:///./dev.db"
    anthropic_api_key: str = ""
    redis_url: str = "redis://redis:6379/0"
    rapidapi_key: str = ""

    # Authentication
    # Dev-only default; production deploys are blocked at startup via the
    # RENDER/FLY guard at the bottom of this module (ruff S105 allowed here).
    secret_key: str = "dev-only-change-me"  # noqa: S105
    admin_email: str = ""
    admin_password: str = ""
    api_key: str = ""  # API key for programmatic access (MCP server)

    # Follow-up reminders
    followup_reminder_days: int = 5

    # Cloudflare R2 (file upload)
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_endpoint_url: str = ""
    r2_bucket_name: str = "jobsearch-files"
    # Cloudflare R2 expects the literal "auto"; keeping this as a setting lets
    # us target mock S3 endpoints in tests without changing code.
    r2_region: str = "auto"

    # Sentry (error tracking)
    sentry_dsn: str = ""

    # Resend (document reminder emails)
    resend_api_key: str = ""
    resend_from_email: str = "noreply@jobsearches.cc"
    document_reminder_email: str = "marco.bellingeri@gmail.com"

    # Input limits
    max_cv_size: int = 100_000  # ~100KB chars
    max_job_desc_size: int = 50_000  # ~50KB chars
    max_batch_size: int = 10  # Hard limit: max items per batch (free tier constraint)

    # CORS
    cors_allowed_origins: str = "http://localhost,http://localhost:80"
    cors_allow_credentials: bool = True

    # Security
    trusted_hosts: str = "localhost,127.0.0.1"
    rate_limit_default: str = "60/minute"
    rate_limit_analyze: str = "10/minute"

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse comma-separated CORS origins into a list."""
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def trusted_hosts_list(self) -> list[str]:
        """Parse comma-separated trusted hosts into a list."""
        return [h.strip() for h in self.trusted_hosts.split(",") if h.strip()]

    @property
    def effective_database_url(self) -> str:
        """Normalize DATABASE_URL for SQLAlchemy compatibility.

        - Converts postgres:// to postgresql:// (Neon/Heroku use old prefix)
        - Strips channel_binding param (unsupported by psycopg2)
        - Passes through non-postgresql URLs unchanged (e.g. sqlite for CI)
        """
        url = self.database_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        if not url.startswith("postgresql://"):
            return url
        from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        params.pop("channel_binding", None)
        clean_query = urlencode({k: v[0].strip() for k, v in params.items()})
        return urlunparse(parsed._replace(query=clean_query))

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()

# Prevent deployment with default secret key
if settings.secret_key == "dev-only-change-me" and _os.environ.get("RENDER"):  # noqa: S105
    # The dev default string is intentionally duplicated here (ruff S105) — it's the
    # exact sentinel we need to refuse at boot when running on Render.
    raise RuntimeError("SECRET_KEY must be set to a secure random value in production")
