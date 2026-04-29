"""Tests for full pg_dump backup pipeline (db_dump.create_pg_dump_backup).

Uses mocked subprocess + boto3 — we don't shell out to a real pg_dump or
upload to real R2 in tests. The dump-streaming logic is exercised with
synthetic SQL bytes; the gzip + R2 upload + cleanup paths are verified
via mock call assertions.
"""

import gzip
import subprocess
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.integrations.db_dump import (
    MAX_PG_DUMPS,
    PG_DUMP_PREFIX,
    _cleanup_old_pg_dumps,
    _resolve_pg_dump_binary,
    create_pg_dump_backup,
    list_pg_dumps,
)


class TestResolvePgDumpBinary:
    def test_raises_when_missing(self):
        with (
            patch("src.integrations.db_dump.shutil.which", return_value=None),
            pytest.raises(RuntimeError, match="pg_dump binary not found"),
        ):
            _resolve_pg_dump_binary()

    def test_returns_path_when_present(self):
        with patch("src.integrations.db_dump.shutil.which", return_value="/usr/bin/pg_dump"):
            assert _resolve_pg_dump_binary() == "/usr/bin/pg_dump"


@patch("src.integrations.r2._get_r2_client")
@patch("src.integrations.db_dump.subprocess.run")
@patch("src.integrations.db_dump.shutil.which", return_value="/usr/bin/pg_dump")
class TestCreatePgDumpBackupHappyPath:
    def test_uploads_gzipped_dump_and_returns_metadata(self, _which, mock_run, mock_get_client):
        # 5 KB of synthetic SQL — enough to clear MIN_DUMP_BYTES.
        sql_bytes = b"-- pg_dump output\n" + (b"INSERT INTO t VALUES (1);\n" * 200)
        mock_run.return_value = MagicMock(returncode=0, stdout=sql_bytes, stderr=b"")
        mock_client = MagicMock()
        mock_client.list_objects_v2.return_value = {"Contents": []}
        mock_get_client.return_value = mock_client

        # Patch settings.r2_bucket_name so the call doesn't depend on
        # whatever the test env set.
        with patch("src.integrations.db_dump.settings") as mock_settings:
            mock_settings.database_url = "postgresql://u:p@h/db"
            mock_settings.r2_bucket_name = "test-bucket"
            result = create_pg_dump_backup()

        # Subprocess called with the right pg_dump args (no shell=True).
        call_args = mock_run.call_args
        cmd = call_args.args[0]
        assert cmd[0] == "/usr/bin/pg_dump"
        assert "postgresql://u:p@h/db" in cmd
        assert "--no-owner" in cmd
        assert "--no-privileges" in cmd
        assert "--format=plain" in cmd

        # R2 put_object received gzipped bytes that decompress back to
        # the original SQL — proves we didn't mangle the stream.
        put_call = mock_client.put_object.call_args
        assert put_call.kwargs["Bucket"] == "test-bucket"
        assert put_call.kwargs["Key"].startswith(PG_DUMP_PREFIX)
        assert put_call.kwargs["Key"].endswith(".sql.gz")
        assert put_call.kwargs["ContentType"] == "application/gzip"
        assert gzip.decompress(put_call.kwargs["Body"]) == sql_bytes

        # Metadata sanity.
        assert result["key"] == put_call.kwargs["Key"]
        assert result["size_kb"] > 0
        assert result["original_size_kb"] >= result["size_kb"]
        assert "exported_at" in result

    def test_uses_explicit_database_url_override(self, _which, mock_run, mock_get_client):
        sql_bytes = b"SELECT 1;\n" * 50
        mock_run.return_value = MagicMock(returncode=0, stdout=sql_bytes, stderr=b"")
        mock_client = MagicMock()
        mock_client.list_objects_v2.return_value = {"Contents": []}
        mock_get_client.return_value = mock_client

        with patch("src.integrations.db_dump.settings") as mock_settings:
            mock_settings.database_url = "postgresql://default/db"
            mock_settings.r2_bucket_name = "test-bucket"
            create_pg_dump_backup(database_url="postgresql://override/db")

        cmd = mock_run.call_args.args[0]
        assert "postgresql://override/db" in cmd
        assert "postgresql://default/db" not in cmd


@patch("src.integrations.r2._get_r2_client")
@patch("src.integrations.db_dump.subprocess.run")
@patch("src.integrations.db_dump.shutil.which", return_value="/usr/bin/pg_dump")
class TestCreatePgDumpBackupErrors:
    def test_raises_on_non_zero_exit(self, _which, mock_run, _get_client):
        mock_run.return_value = MagicMock(returncode=1, stdout=b"", stderr=b"could not connect to server")
        with patch("src.integrations.db_dump.settings") as mock_settings:
            mock_settings.database_url = "postgresql://u:p@h/db"
            with pytest.raises(RuntimeError, match="exit code 1"):
                create_pg_dump_backup()

    def test_raises_on_empty_output(self, _which, mock_run, _get_client):
        mock_run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
        with patch("src.integrations.db_dump.settings") as mock_settings:
            mock_settings.database_url = "postgresql://u:p@h/db"
            with pytest.raises(RuntimeError, match="empty or truncated"):
                create_pg_dump_backup()

    def test_raises_on_truncated_output(self, _which, mock_run, _get_client):
        # Below MIN_DUMP_BYTES — defensive against silent pg_dump failures
        # that exit 0 but produce only a header.
        mock_run.return_value = MagicMock(returncode=0, stdout=b"-- short\n", stderr=b"")
        with patch("src.integrations.db_dump.settings") as mock_settings:
            mock_settings.database_url = "postgresql://u:p@h/db"
            with pytest.raises(RuntimeError, match="empty or truncated"):
                create_pg_dump_backup()

    def test_raises_on_timeout(self, _which, mock_run, _get_client):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["pg_dump"], timeout=600)
        with patch("src.integrations.db_dump.settings") as mock_settings:
            mock_settings.database_url = "postgresql://u:p@h/db"
            with pytest.raises(RuntimeError, match="timed out"):
                create_pg_dump_backup()

    def test_raises_when_database_url_empty(self, _which, _run, _get_client):
        with patch("src.integrations.db_dump.settings") as mock_settings:
            mock_settings.database_url = ""
            with pytest.raises(RuntimeError, match="DATABASE_URL not configured"):
                create_pg_dump_backup()


class TestCleanupOldPgDumps:
    def test_no_cleanup_under_threshold(self):
        client = MagicMock()
        now = datetime.now(UTC)
        client.list_objects_v2.return_value = {
            "Contents": [
                {
                    "Key": f"{PG_DUMP_PREFIX}{i}.sql.gz",
                    "Size": 1024,
                    "LastModified": now - timedelta(days=i),
                }
                for i in range(MAX_PG_DUMPS)
            ]
        }
        with patch("src.integrations.db_dump.settings") as mock_settings:
            mock_settings.r2_bucket_name = "b"
            assert _cleanup_old_pg_dumps(client) == 0
        client.delete_objects.assert_not_called()

    def test_deletes_excess(self):
        client = MagicMock()
        now = datetime.now(UTC)
        # MAX + 3 = 3 to delete (the oldest 3).
        objects = [
            {
                "Key": f"{PG_DUMP_PREFIX}{i}.sql.gz",
                "Size": 1024,
                "LastModified": now - timedelta(days=i),
            }
            for i in range(MAX_PG_DUMPS + 3)
        ]
        client.list_objects_v2.return_value = {"Contents": objects}

        with patch("src.integrations.db_dump.settings") as mock_settings:
            mock_settings.r2_bucket_name = "b"
            assert _cleanup_old_pg_dumps(client) == 3

        delete_call = client.delete_objects.call_args
        deleted_keys = {o["Key"] for o in delete_call.kwargs["Delete"]["Objects"]}
        # Oldest 3 (highest day deltas) should be the ones deleted.
        expected = {f"{PG_DUMP_PREFIX}{i}.sql.gz" for i in (MAX_PG_DUMPS, MAX_PG_DUMPS + 1, MAX_PG_DUMPS + 2)}
        assert deleted_keys == expected

    def test_ignores_non_sql_gz_files(self):
        client = MagicMock()
        now = datetime.now(UTC)
        # 6 .json.gz (JSON backups) + 0 .sql.gz → no .sql.gz to cleanup.
        client.list_objects_v2.return_value = {
            "Contents": [
                {
                    "Key": f"backups/2026-04-29/{i:06d}.json.gz",
                    "Size": 1024,
                    "LastModified": now - timedelta(days=i),
                }
                for i in range(MAX_PG_DUMPS + 5)
            ]
        }
        with patch("src.integrations.db_dump.settings") as mock_settings:
            mock_settings.r2_bucket_name = "b"
            assert _cleanup_old_pg_dumps(client) == 0
        client.delete_objects.assert_not_called()


@patch("src.integrations.r2._get_r2_client")
class TestListPgDumps:
    def test_returns_sql_gz_only_newest_first(self, mock_get_client):
        client = MagicMock()
        old = datetime.now(UTC) - timedelta(days=5)
        new = datetime.now(UTC)
        client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": f"{PG_DUMP_PREFIX}old.sql.gz", "Size": 1024, "LastModified": old},
                {"Key": f"{PG_DUMP_PREFIX}new.sql.gz", "Size": 2048, "LastModified": new},
                {"Key": f"{PG_DUMP_PREFIX}readme.txt", "Size": 100, "LastModified": new},
            ]
        }
        mock_get_client.return_value = client
        with patch("src.integrations.db_dump.settings") as mock_settings:
            mock_settings.r2_bucket_name = "b"
            result = list_pg_dumps()

        assert len(result) == 2
        assert result[0]["key"].endswith("new.sql.gz")
        assert result[1]["key"].endswith("old.sql.gz")
        assert result[0]["size_kb"] == 2.0

    def test_returns_empty_on_error(self, mock_get_client):
        mock_get_client.side_effect = RuntimeError("R2 unconfigured")
        assert list_pg_dumps() == []
