"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    database_url: str = "postgresql://jobsearch:jobsearch@db:5432/jobsearch"
    anthropic_api_key: str = ""
    redis_url: str = "redis://redis:6379/0"
    rapidapi_key: str = ""

    # Authentication
    secret_key: str = "change-me-to-a-random-string"
    admin_email: str = ""
    admin_password: str = ""

    # Email notifications
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    notification_email: str = "marco.bellingeri@gmail.com"
    followup_reminder_days: int = 5

    # CORS
    cors_allowed_origins: str = "http://localhost,http://localhost:80"
    cors_allow_credentials: bool = True

    # Security
    trusted_hosts: str = "*"
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
        """Fly Postgres uses postgres:// but SQLAlchemy requires postgresql://."""
        url = self.database_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
