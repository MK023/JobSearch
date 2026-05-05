"""Test che ``_run_migrations()`` applica Alembic upgrade su entrambi i DB.

Mocka ``command.upgrade`` per verificare:
- Primary DB (Pulse) sempre eseguito.
- Secondary DB (Worldwild) eseguito SOLO se ``effective_worldwild_database_url``
  non è vuoto.
"""

from __future__ import annotations

from unittest.mock import patch


def test_run_migrations_runs_only_primary_when_worldwild_unset() -> None:
    """Senza worldwild URL, command.upgrade chiamato 1 sola volta (primary)."""
    from src.main import _run_migrations

    with (
        patch("src.main.settings") as mock_settings,
        patch("alembic.command.upgrade") as mock_upgrade,
    ):
        mock_settings.effective_database_url = "postgresql://primary/db"
        mock_settings.effective_worldwild_database_url = ""  # secondary non configurato
        _run_migrations()

    assert mock_upgrade.call_count == 1


def test_run_migrations_runs_both_when_worldwild_configured() -> None:
    """Con worldwild URL settato, command.upgrade chiamato 2 volte."""
    from src.main import _run_migrations

    with (
        patch("src.main.settings") as mock_settings,
        patch("alembic.command.upgrade") as mock_upgrade,
    ):
        mock_settings.effective_database_url = "postgresql://primary/db"
        mock_settings.effective_worldwild_database_url = "postgresql://secondary/worldwild"
        _run_migrations()

    assert mock_upgrade.call_count == 2


def test_run_migrations_passes_correct_script_locations() -> None:
    """Verifica i due script_location distinti: ``alembic`` e ``alembic_worldwild``."""
    from src.main import _run_migrations

    with (
        patch("src.main.settings") as mock_settings,
        patch("alembic.command.upgrade") as mock_upgrade,
    ):
        mock_settings.effective_database_url = "postgresql://primary/db"
        mock_settings.effective_worldwild_database_url = "postgresql://secondary/worldwild"
        _run_migrations()

    # Estrai i script_location dei 2 Config oggetti passati a upgrade()
    script_locations = []
    for call in mock_upgrade.call_args_list:
        cfg = call.args[0]
        script_locations.append(cfg.get_main_option("script_location"))

    assert any(loc.endswith("alembic") for loc in script_locations)
    assert any(loc.endswith("alembic_worldwild") for loc in script_locations)


def test_run_migrations_passes_correct_db_urls() -> None:
    """Verifica che le sqlalchemy.url siano i due DB distinti."""
    from src.main import _run_migrations

    with (
        patch("src.main.settings") as mock_settings,
        patch("alembic.command.upgrade") as mock_upgrade,
    ):
        mock_settings.effective_database_url = "postgresql://primary/db"
        mock_settings.effective_worldwild_database_url = "postgresql://secondary/worldwild"
        _run_migrations()

    db_urls = []
    for call in mock_upgrade.call_args_list:
        cfg = call.args[0]
        db_urls.append(cfg.get_main_option("sqlalchemy.url"))

    assert "postgresql://primary/db" in db_urls
    assert "postgresql://secondary/worldwild" in db_urls
