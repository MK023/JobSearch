"""Application configuration via environment variables."""

import os as _os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    database_url: str = "postgresql://jobsearch:jobsearch@db:5432/jobsearch"
    anthropic_api_key: str = ""
    redis_url: str = "redis://redis:6379/0"
    rapidapi_key: str = ""

    # Authentication
    secret_key: str = "dev-only-change-me"  # noqa: S105 — dev default, blocked in prod by RENDER/FLY guard
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

        - Converts postgres:// to postgresql:// (Fly/Neon use old prefix)
        - Strips channel_binding param (unsupported by psycopg2)
        """
        from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

        url = self.database_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        params.pop("channel_binding", None)
        clean_query = urlencode({k: v[0] for k, v in params.items()})
        return urlunparse(parsed._replace(query=clean_query))

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()

# Prevent deployment with default secret key
_is_render = bool(_os.environ.get("RENDER"))
_is_flyio = bool(_os.environ.get("FLY_APP_NAME"))
if settings.secret_key == "dev-only-change-me" and (_is_render or _is_flyio):  # noqa: S105
    raise RuntimeError("SECRET_KEY must be set to a secure random value in production")
