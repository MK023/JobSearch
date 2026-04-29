"""Application configuration via environment variables.

Optional multi-env switcher: setting ``JOBSEARCH_ENV=<name>`` makes the
loader read ``config.toml`` at the repo root and apply the
``[env.<name>]`` section as env-var overrides *before* Pydantic
constructs ``Settings``. This lets a single var flip the entire wiring
(DB / Redis / etc.) for offline dev or disaster recovery without
manually exporting half a dozen variables.

In prod (Render), ``JOBSEARCH_ENV`` is unset → the loader is a no-op
and the dashboard env vars remain authoritative.
"""

import os as _os
from pathlib import Path as _Path

from pydantic_settings import BaseSettings


def _resolve_toml_path() -> _Path:
    """Repo-root ``config.toml``. Extracted for monkeypatching in tests."""
    return _Path(__file__).resolve().parent.parent.parent / "config.toml"


def _apply_toml_env_overrides() -> None:
    """Apply ``[env.<JOBSEARCH_ENV>]`` overrides from ``config.toml``.

    No-op when:
    - ``JOBSEARCH_ENV`` is unset or empty (production path).
    - ``config.toml`` is missing (e.g. in CI test runs that don't ship it).
    - The selected section doesn't exist (typo/unknown env name).

    TOML wins over pre-existing env vars on purpose: the whole point of
    setting ``JOBSEARCH_ENV=local`` is to override the dev shell's
    ``DATABASE_URL`` (which might still point at prod) without making
    the user remember to ``unset`` it.
    """
    env_name = _os.environ.get("JOBSEARCH_ENV", "").strip()
    if not env_name:
        return
    toml_path = _resolve_toml_path()
    if not toml_path.exists():
        return
    try:
        import tomllib  # stdlib in 3.11+
    except ImportError:
        return
    with toml_path.open("rb") as f:
        data = tomllib.load(f)
    section = data.get("env", {}).get(env_name, {})
    if not section:
        return
    for key, val in section.items():
        _os.environ[key.upper()] = str(val)


_apply_toml_env_overrides()


def _normalize_postgres_url(url: str) -> str:
    """Convert legacy ``postgres://`` to ``postgresql://`` and drop unsupported params.

    Pass-through for empty strings and non-postgresql schemes (e.g. sqlite for CI).
    """
    if not url:
        return url
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

    # WorldWild — secondary DB (Supabase) for external job-board ingestion.
    # Empty string disables the WorldWild ingest layer entirely (graceful skip
    # on routes + cron). Production deploys override via env var on Render.
    worldwild_database_url: str = ""

    # Adzuna API (worldwild ingest source #1)
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""

    # Pre-AI gate threshold for WorldWild promotion. When stack-match score
    # against Marco's CV is BELOW this value (0-100), the promotion path
    # skips the Anthropic analyzer call and marks the Decision as
    # ``skipped_low_match``. 50 is a neutral default — half the offer's
    # tech overlaps the CV. Tuned later from the ``decisions`` history
    # in PR #5 once we have ~50 manual samples.
    promote_score_threshold: int = 50

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
        return _normalize_postgres_url(self.database_url)

    @property
    def effective_worldwild_database_url(self) -> str:
        """Normalize WORLDWILD_DATABASE_URL for SQLAlchemy compatibility.

        Same normalization as the primary URL. Returns empty string when the
        secondary DB is disabled, so callers can short-circuit cleanly.
        """
        return _normalize_postgres_url(self.worldwild_database_url)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()

# Prevent deployment with default secret key
if settings.secret_key == "dev-only-change-me" and _os.environ.get("RENDER"):  # noqa: S105
    # The dev default string is intentionally duplicated here (ruff S105) — it's the
    # exact sentinel we need to refuse at boot when running on Render.
    raise RuntimeError("SECRET_KEY must be set to a secure random value in production")
