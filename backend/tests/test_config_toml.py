"""Tests for the TOML-based multi-env config switcher.

Exercises ``_apply_toml_env_overrides`` directly — much simpler than
trying to assert on ``Settings`` after import (which already ran the
side-effect at module load).

Each test isolates env vars + toml file path via monkeypatch, so
running this suite never bleeds into the parent process's env or
touches the real ``config.toml`` at the repo root.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src import config


def _write_toml(path: Path, body: str) -> Path:
    path.write_text(textwrap.dedent(body))
    return path


@pytest.fixture
def fake_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Empty TOML at a tmp path, wired into the loader via monkeypatch."""
    toml = tmp_path / "config.toml"
    toml.write_text("")
    monkeypatch.setattr(config, "_resolve_toml_path", lambda: toml)
    return toml


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip the env vars the loader writes — tests must start clean."""
    for k in ("JOBSEARCH_ENV", "DATABASE_URL", "REDIS_URL", "WORLDWILD_DATABASE_URL"):
        monkeypatch.delenv(k, raising=False)


class TestApplyTomlEnvOverrides:
    def test_no_env_var_is_noop(self, fake_toml: Path):
        _write_toml(
            fake_toml,
            """
            [env.local]
            database_url = "postgresql://test/local"
            """,
        )
        config._apply_toml_env_overrides()
        # JOBSEARCH_ENV unset → loader exits early, never reads the toml.
        assert "DATABASE_URL" not in pytest.importorskip("os").environ

    def test_local_env_overrides_database_url(self, fake_toml: Path, monkeypatch: pytest.MonkeyPatch):
        _write_toml(
            fake_toml,
            """
            [env.local]
            database_url = "postgresql://override/local"
            redis_url    = "redis://localhost:6379/0"
            """,
        )
        monkeypatch.setenv("JOBSEARCH_ENV", "local")
        config._apply_toml_env_overrides()
        import os as _os

        assert _os.environ["DATABASE_URL"] == "postgresql://override/local"
        assert _os.environ["REDIS_URL"] == "redis://localhost:6379/0"

    def test_toml_wins_over_existing_env(self, fake_toml: Path, monkeypatch: pytest.MonkeyPatch):
        # Pre-existing DATABASE_URL (e.g. dev shell pointing at prod) must
        # be overwritten by the TOML — this is the whole point of the
        # JOBSEARCH_ENV=local muscle memory.
        monkeypatch.setenv("DATABASE_URL", "postgresql://prod/leftover")
        _write_toml(
            fake_toml,
            """
            [env.local]
            database_url = "postgresql://override/local"
            """,
        )
        monkeypatch.setenv("JOBSEARCH_ENV", "local")
        config._apply_toml_env_overrides()
        import os as _os

        assert _os.environ["DATABASE_URL"] == "postgresql://override/local"

    def test_unknown_section_is_noop(self, fake_toml: Path, monkeypatch: pytest.MonkeyPatch):
        _write_toml(
            fake_toml,
            """
            [env.local]
            database_url = "postgresql://override/local"
            """,
        )
        monkeypatch.setenv("JOBSEARCH_ENV", "typo-nonexistent")
        config._apply_toml_env_overrides()
        import os as _os

        assert "DATABASE_URL" not in _os.environ

    def test_missing_toml_file_is_noop(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        # Loader must survive when config.toml is absent (CI test runs).
        missing = tmp_path / "does-not-exist.toml"
        monkeypatch.setattr(config, "_resolve_toml_path", lambda: missing)
        monkeypatch.setenv("JOBSEARCH_ENV", "local")
        config._apply_toml_env_overrides()
        import os as _os

        assert "DATABASE_URL" not in _os.environ

    def test_keys_uppercased(self, fake_toml: Path, monkeypatch: pytest.MonkeyPatch):
        # TOML keys are conventionally lowercase; the loader uppercases
        # them so they match Pydantic Settings's env-var convention.
        _write_toml(
            fake_toml,
            """
            [env.dr]
            worldwild_database_url = "postgresql://dr/worldwild"
            """,
        )
        monkeypatch.setenv("JOBSEARCH_ENV", "dr")
        config._apply_toml_env_overrides()
        import os as _os

        assert _os.environ["WORLDWILD_DATABASE_URL"] == "postgresql://dr/worldwild"
