"""Alembic environment for the WorldWild secondary DB (Supabase).

Mirrors ``alembic/env.py`` but anchored to ``WorldwildBase.metadata`` and reads
its URL from ``WORLDWILD_DATABASE_URL`` (via ``settings.effective_worldwild_database_url``).

If the env var is not set, this script aborts with a clear error rather than
falling back to the placeholder URL in ``alembic.ini``.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from src.config import settings

# Import all WorldWild models so Alembic autogenerate sees them.
from src.database.worldwild_db import WorldwildBase
from src.worldwild import (
    audit_models,  # noqa: F401  -- registers audit_logs (mirror)
    models,  # noqa: F401  -- registers job_offers, decisions, adapter_runs
)

config = context.config

_url = settings.effective_worldwild_database_url
if not _url:
    raise RuntimeError(
        "WORLDWILD_DATABASE_URL is not set — refusing to run migrations against "
        "the placeholder URL in alembic.ini. Export the env var first."
    )

config.set_main_option("sqlalchemy.url", _url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = WorldwildBase.metadata


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
