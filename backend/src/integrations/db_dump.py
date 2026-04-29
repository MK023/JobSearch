"""Full pg_dump backup to Cloudflare R2 — disaster-recovery pipeline.

Captures the entire DB (schema + data + sequences + FKs + ENUMs) via
``pg_dump --format=plain --no-owner --no-privileges``, gzip-compresses
the SQL stream, and uploads it to R2 under
``backups-pg/{YYYY-MM-DD}/{HHMMSS}.sql.gz``.

Restore is a one-liner::

    gunzip -c dump.sql.gz | psql "$TARGET_URL" \
        --single-transaction --set ON_ERROR_STOP=on

This is the disaster-recovery counterpart to ``backup.py`` (which only
exports 7 critical tables as JSON). Both pipelines coexist for now —
the JSON one is faster and lets the UI restore individual tables, while
``pg_dump`` catches everything: ``users``, ``linkedin_applications``,
``audit_logs``, ``inbox_items``, ``alembic_version``, ENUMs, sequences,
foreign keys, indexes.

Driven by the 29 April 2026 incident: Neon free-tier compute exhausted
at 100% forced a live migration to Supabase. We invoked ``pg_dump``
manually because the JSON backup was missing 16 of 23 tables. Lesson:
"backup" must mean "restore the entire DB in one command".

Capacity assumption: the in-memory buffer fits the dump. With the
JobSearch DB at ~16 MB on disk → ~5 MB compressed SQL, this is safe on
Render's 512 MB free-tier RAM. If the DB grows past ~200 MB SQL, switch
to a streaming ``subprocess.Popen`` + chunked gzip pipeline.
"""

import gzip
import logging
import shutil
import subprocess
from datetime import UTC, datetime
from typing import Any

from ..config import settings

logger = logging.getLogger(__name__)

# Retention: 14 archives = 2 weeks of point-in-time recovery on the
# daily cadence (`.github/workflows/daily-backup-pg-dump.yml`). At
# ~5 MB compressed per archive, R2 storage stays around 70 MB — well
# under the free-tier 10 GB. Bumped from 5 when the cron moved from
# weekly to daily; with retention 5 we'd have lost everything older
# than 5 days, defeating the point of more frequent backups.
MAX_PG_DUMPS = 14
PG_DUMP_PREFIX = "backups-pg/"
PG_DUMP_TIMEOUT_SECONDS = 600
MIN_DUMP_BYTES = 100


def _resolve_pg_dump_binary() -> str:
    """Return the absolute path to pg_dump, or raise if missing.

    Pinned to PG 17 in the Dockerfile, but we accept whatever's on PATH —
    a dev box might have a different version installed system-wide.
    Surface the error early instead of letting subprocess fail with a
    cryptic ENOENT inside the request handler.
    """
    path = shutil.which("pg_dump")
    if path is None:
        raise RuntimeError("pg_dump binary not found on PATH. Install postgresql-client-17 (matches the server major).")
    return path


def create_pg_dump_backup(database_url: str | None = None) -> dict[str, Any]:
    """Run pg_dump on the live DB and upload a gzipped SQL archive to R2.

    Args:
        database_url: Override URL for the dump source. Defaults to
            ``settings.database_url`` (the primary DB).

    Returns:
        Dict with ``key``, ``size_kb``, ``original_size_kb``,
        ``exported_at`` (ISO-8601 UTC).

    Raises:
        RuntimeError: pg_dump missing, R2 unconfigured, dump timed out,
            non-zero exit, or empty output.
    """
    pg_dump = _resolve_pg_dump_binary()
    url = (database_url or settings.database_url or "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL not configured.")

    now = datetime.now(UTC)
    cmd = [
        pg_dump,
        url,
        "--no-owner",
        "--no-privileges",
        "--no-publications",
        "--no-subscriptions",
        "--format=plain",
    ]

    logger.info("pg_dump backup: starting")
    try:
        proc = subprocess.run(  # noqa: S603 — args list, shell=False, no user input
            cmd,
            capture_output=True,
            timeout=PG_DUMP_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"pg_dump timed out after {PG_DUMP_TIMEOUT_SECONDS}s") from e

    if proc.returncode != 0:
        # Truncate stderr to avoid leaking the full URL (which may appear
        # in pg_dump error messages on connection failure).
        stderr_tail = (proc.stderr or b"").decode("utf-8", "replace")[-400:]
        logger.error("pg_dump exit %s: %s", proc.returncode, stderr_tail)
        raise RuntimeError(f"pg_dump failed with exit code {proc.returncode}")

    sql_bytes = proc.stdout
    if not sql_bytes or len(sql_bytes) < MIN_DUMP_BYTES:
        raise RuntimeError("pg_dump produced empty or truncated output.")

    compressed = gzip.compress(sql_bytes, compresslevel=6)
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H%M%S")
    r2_key = f"{PG_DUMP_PREFIX}{date_str}/{time_str}.sql.gz"

    from .r2 import _get_r2_client

    client = _get_r2_client()
    client.put_object(
        Bucket=settings.r2_bucket_name,
        Key=r2_key,
        Body=compressed,
        ContentType="application/gzip",
    )

    size_kb = round(len(compressed) / 1024, 1)
    original_size_kb = round(len(sql_bytes) / 1024, 1)
    logger.info(
        "pg_dump backup uploaded: %s (%s KB compressed, %s KB raw)",
        r2_key,
        size_kb,
        original_size_kb,
    )

    _cleanup_old_pg_dumps(client)

    return {
        "key": r2_key,
        "size_kb": size_kb,
        "original_size_kb": original_size_kb,
        "exported_at": now.isoformat(),
    }


def list_pg_dumps() -> list[dict[str, Any]]:
    """List existing full pg_dump backups in R2 (newest first)."""
    try:
        from .r2 import _get_r2_client

        client = _get_r2_client()
        response = client.list_objects_v2(
            Bucket=settings.r2_bucket_name,
            Prefix=PG_DUMP_PREFIX,
        )
        contents = response.get("Contents", [])
        return [
            {
                "key": obj["Key"],
                "size_kb": round(obj["Size"] / 1024, 1),
                "last_modified": obj["LastModified"].isoformat(),
            }
            for obj in sorted(contents, key=lambda x: x["LastModified"], reverse=True)
            if obj["Key"].endswith(".sql.gz")
        ]
    except Exception:
        logger.exception("Failed to list pg_dump backups from R2")
        return []


def _cleanup_old_pg_dumps(client: Any) -> int:
    """Remove pg_dump backups beyond MAX_PG_DUMPS. Returns count deleted."""
    try:
        response = client.list_objects_v2(
            Bucket=settings.r2_bucket_name,
            Prefix=PG_DUMP_PREFIX,
        )
        contents = response.get("Contents", [])
        gz_files = sorted(
            [obj for obj in contents if obj["Key"].endswith(".sql.gz")],
            key=lambda x: x["LastModified"],
            reverse=True,
        )
        if len(gz_files) <= MAX_PG_DUMPS:
            return 0

        to_delete = gz_files[MAX_PG_DUMPS:]
        objects = [{"Key": obj["Key"]} for obj in to_delete]
        client.delete_objects(
            Bucket=settings.r2_bucket_name,
            Delete={"Objects": objects},
        )
        logger.info("Cleaned up %d old pg_dump backups", len(objects))
        return len(objects)
    except Exception:
        logger.exception("Failed to cleanup old pg_dump backups")
        return 0
