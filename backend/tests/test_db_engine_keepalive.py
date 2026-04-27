"""Verify the database engine wires TCP keepalives on PostgreSQL.

Sentry surfaced ``OperationalError: SSL connection has been closed
unexpectedly`` on long-running batch endpoints (JOBSEARCH-E, regressed
2026-04-27). The fix sets psycopg2 ``keepalives_*`` connect args so
the kernel keeps idle SSL sockets alive even when the request is busy
elsewhere (e.g. waiting on Anthropic).

These tests guard the wiring: keepalives present for PostgreSQL,
absent for SQLite (test runs on in-memory SQLite where the args
would be a no-op at best, an error at worst).
"""

from __future__ import annotations

from importlib import reload
from unittest.mock import patch


def _reload_base_with_url(url: str):
    """Reload ``src.database.base`` with a patched DB URL so we can
    inspect the engine's connect_args without touching the live engine
    other tests share. ``effective_database_url`` is a Pydantic property
    that derives from ``database_url``, so we patch the underlying field."""
    from src import config
    from src.database import base as db_base

    with patch.object(config.settings, "database_url", url):
        reload(db_base)
        return db_base


class TestEngineKeepalive:
    def test_postgresql_url_enables_keepalives(self):
        db_base = _reload_base_with_url("postgresql://user:pw@host:5432/db")
        try:
            assert db_base._connect_args == {
                "keepalives": 1,
                "keepalives_idle": 30,
                "keepalives_interval": 10,
                "keepalives_count": 5,
            }
        finally:
            # Restore the live engine for subsequent tests in the session.
            _reload_base_with_url("sqlite:///:memory:")

    def test_postgresql_plus_psycopg2_url_enables_keepalives(self):
        """SQLAlchemy accepts both ``postgresql://`` and the explicit
        ``postgresql+psycopg2://`` form. Both must take the keepalive
        path."""
        db_base = _reload_base_with_url("postgresql+psycopg2://u:p@h/db")
        try:
            assert "keepalives" in db_base._connect_args
        finally:
            _reload_base_with_url("sqlite:///:memory:")

    def test_sqlite_url_omits_keepalives(self):
        """SQLite has no socket — passing keepalive args would either
        be silently ignored or raise depending on the driver. We omit
        them entirely."""
        db_base = _reload_base_with_url("sqlite:///:memory:")
        assert db_base._connect_args == {}
