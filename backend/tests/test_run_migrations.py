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


class TestSecondaryDbDegrada:
    """Un secondario irraggiungibile deve degradare l'ingestion, non spegnere l'app.

    Il 16/07/2026 il progetto Supabase di WorldWild è andato in pausa per
    inattività (free tier: pausa dopo 7 giorni di basso traffico) mentre il
    primario "Pulse" era vivo. Risultato: ``command.upgrade`` sul secondario
    ha sollevato al boot, l'eccezione è risalita nel ``lifespan`` e l'app
    non è partita affatto — con Pulse perfettamente sano.

    Il design dice che il secondario è opzionale: ``worldwild_db.py`` lo
    lascia ``None`` quando non è configurato, e ``dual_audit()`` avvolge ogni
    scrittura in un try/except separato perché *"perdere una delle due copie
    è accettabile, bloccare l'azione no"*. Quella resilienza però esisteva
    solo a runtime: al boot non c'era, e un DB dichiarato opzionale diventava
    un single point of failure.

    Asimmetria voluta: il PRIMARIO che non risponde resta fatale — senza di
    lui non c'è app da servire, meglio un boot fallito che un 500 a ogni
    richiesta.
    """

    def test_worldwild_in_pausa_non_impedisce_il_boot(self, caplog) -> None:
        """Secondario giù: si logga e si tira dritto."""
        from src.main import _run_migrations

        def _fail_on_secondary(cfg, rev):
            if cfg.get_main_option("script_location").endswith("alembic_worldwild"):
                raise OSError("connection to server failed: project is paused")

        with (
            patch("src.main.settings") as mock_settings,
            patch("alembic.command.upgrade", side_effect=_fail_on_secondary) as mock_upgrade,
        ):
            mock_settings.effective_database_url = "postgresql://primary/db"
            mock_settings.effective_worldwild_database_url = "postgresql://secondary/worldwild"
            _run_migrations()  # non deve sollevare

        assert mock_upgrade.call_count == 2, "il primario deve essere stato migrato comunque"
        assert any(r.levelname in ("WARNING", "ERROR") for r in caplog.records), (
            "il fallimento del secondario deve lasciare traccia: LoggingIntegration "
            "manda a Sentry da WARNING in su, un fallimento silenzioso sarebbe peggio del bug"
        )

    def test_primario_giu_resta_fatale(self) -> None:
        """Senza primario non c'è app: l'errore deve risalire e fermare il boot."""
        import pytest

        from src.main import _run_migrations

        def _fail_on_primary(cfg, rev):
            if cfg.get_main_option("script_location").endswith("alembic"):
                raise OSError("connection to server failed: primary unreachable")

        with (
            patch("src.main.settings") as mock_settings,
            patch("alembic.command.upgrade", side_effect=_fail_on_primary),
            pytest.raises(OSError, match="primary unreachable"),
        ):
            mock_settings.effective_database_url = "postgresql://primary/db"
            mock_settings.effective_worldwild_database_url = "postgresql://secondary/worldwild"
            _run_migrations()
