"""Alembic environment configuration."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from src.config import settings

# Import all models so Alembic can detect them
from src.database.base import Base
from src.auth.models import User  # noqa: F401
from src.cv.models import CVProfile  # noqa: F401
from src.analysis.models import JobAnalysis, AppSettings  # noqa: F401
from src.cover_letter.models import CoverLetter  # noqa: F401
from src.contacts.models import Contact  # noqa: F401
from src.integrations.glassdoor import GlassdoorCache  # noqa: F401
from src.audit.models import AuditLog  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.effective_database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
