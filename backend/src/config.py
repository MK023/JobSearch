import logging
import logging.handlers
import os
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://jobsearch:jobsearch@db:5432/jobsearch"
    anthropic_api_key: str = ""
    redis_url: str = "redis://redis:6379/0"
    credit_budget_usd: float = 5.00

    # Logging
    log_level: str = "INFO"
    log_dir: str = "logs"
    log_max_bytes: int = 10_485_760  # 10 MB
    log_backup_count: int = 5

    model_config = {"env_file": ".env"}


settings = Settings()


def setup_logging() -> None:
    """Configure application-wide logging with rotating file handlers.

    Creates three handlers:
    - Console: INFO+ with brief format (for docker compose logs)
    - app.log: DEBUG+ with detailed format, rotated at 10 MB x 5 backups
    - error.log: ERROR+ only, rotated at 10 MB x 5 backups
    """
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    # --- Console handler (brief, for Docker logs / stdout) ---
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(console)

    # --- Rotating file handler (detailed, all levels) ---
    detail_fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s [%(name)s:%(funcName)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    app_handler = logging.handlers.RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    app_handler.setLevel(logging.DEBUG)
    app_handler.setFormatter(detail_fmt)
    root.addHandler(app_handler)

    # --- Rotating error-only file handler ---
    err_handler = logging.handlers.RotatingFileHandler(
        log_dir / "error.log",
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    err_handler.setLevel(logging.ERROR)
    err_handler.setFormatter(detail_fmt)
    root.addHandler(err_handler)

    # --- Quiet noisy third-party loggers ---
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        "Logging configurato: level=%s, dir=%s, max=%s MB x %d backup",
        settings.log_level, log_dir, settings.log_max_bytes // 1_048_576, settings.log_backup_count,
    )
