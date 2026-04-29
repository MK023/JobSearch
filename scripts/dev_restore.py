#!/usr/bin/env python3
"""Restore the local Docker DB from a pg_dump backup — shadow-prod helper.

Two modes:

1. ``--from-r2`` (default): list ``backups-pg/`` in the configured R2
   bucket, pick the newest ``.sql.gz``, download it, gunzip-stream it
   into ``docker compose exec -T db psql ...``.

2. ``--from-file PATH``: skip R2, use a local archive (e.g. the
   pre-migration dump under ``~/Documents/JobSearch_backups/``).
   Useful when R2 is unreachable, or for the disaster-recovery
   scenario where the only surviving copy is on disk.

Both modes restore inside ``--single-transaction --set ON_ERROR_STOP=on``,
so a partial failure rolls back cleanly and the local DB never ends
up half-populated.

The script is paranoid by default: requires ``--yes`` to actually run
because ``psql --single-transaction`` will happily wipe + replace
existing rows. Always prints the source key/path and the target DB
URL before asking for confirmation.

Usage::

    # Newest backup from R2 (recommended)
    python scripts/dev_restore.py --from-r2 --yes

    # Specific local file (disaster-recovery)
    python scripts/dev_restore.py \\
        --from-file ~/Documents/JobSearch_backups/neon-dump-20260429-pre-supabase-migration.sql.gz \\
        --yes

Env vars required (R2 mode): R2_ENDPOINT_URL, R2_ACCESS_KEY_ID,
R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME. Pulled automatically from a
``.env`` at repo root if present.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _resolve(cmd: str) -> str:
    """Return the absolute path of ``cmd`` or exit with a clear error."""
    path = shutil.which(cmd)
    if path is None:
        sys.exit(f"Required binary not on PATH: {cmd}")
    return path


R2_PREFIX = "backups-pg/"
DEFAULT_DB_USER = "jobsearch"
DEFAULT_DB_NAME = "jobsearch"


def _load_dotenv() -> None:
    """Best-effort .env loader — no python-dotenv dependency."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip("'\""))


def _r2_client():
    import boto3
    from botocore.config import Config

    required = ("R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        sys.exit(f"R2 credentials missing in env: {', '.join(missing)}")

    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _pick_latest_pg_dump(client, bucket: str) -> str:
    response = client.list_objects_v2(Bucket=bucket, Prefix=R2_PREFIX)
    objects = response.get("Contents", [])
    sql_gz = sorted(
        (o for o in objects if o["Key"].endswith(".sql.gz")),
        key=lambda o: o["LastModified"],
        reverse=True,
    )
    if not sql_gz:
        sys.exit(f"No .sql.gz objects under {R2_PREFIX} in bucket {bucket}")
    latest = sql_gz[0]
    print(f"Latest pg_dump in R2: {latest['Key']} ({latest['Size'] / 1024:.1f} KB, {latest['LastModified']})")
    return str(latest["Key"])


def _download_from_r2(client, bucket: str, key: str, dest: Path) -> None:
    print(f"Downloading {key} → {dest} ...")
    client.download_file(bucket, key, str(dest))
    size_kb = dest.stat().st_size / 1024
    print(f"Downloaded {size_kb:.1f} KB")


def _restore_to_docker(archive_gz: Path, db_user: str, db_name: str) -> None:
    """Stream `gunzip -c <file> | docker compose exec -T db psql ...`."""
    print(f"Restoring into Docker DB (user={db_user}, db={db_name}) ...")
    gunzip_bin = _resolve("gunzip")
    docker_bin = _resolve("docker")
    gunzip = subprocess.Popen(  # noqa: S603 — absolute paths via shutil.which, no shell
        [gunzip_bin, "-c", str(archive_gz)],
        stdout=subprocess.PIPE,
    )
    psql = subprocess.run(  # noqa: S603 — absolute paths via shutil.which, no shell
        [
            docker_bin,
            "compose",
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            db_user,
            "-d",
            db_name,
            "--single-transaction",
            "--set",
            "ON_ERROR_STOP=on",
            "--quiet",
        ],
        stdin=gunzip.stdout,
        check=False,
    )
    if gunzip.stdout:
        gunzip.stdout.close()
    gunzip.wait()
    if gunzip.returncode != 0:
        sys.exit(f"gunzip failed with exit {gunzip.returncode}")
    if psql.returncode != 0:
        sys.exit(f"psql restore failed with exit {psql.returncode}")
    print("Restore complete. Local Docker DB now mirrors the source dump.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-r2", action="store_true", help="Pull newest .sql.gz from R2")
    src.add_argument("--from-file", type=Path, help="Use a local .sql.gz archive instead")
    parser.add_argument(
        "--db-user",
        default=os.environ.get("POSTGRES_USER", DEFAULT_DB_USER),
        help="Local Docker DB user (default: $POSTGRES_USER or 'jobsearch')",
    )
    parser.add_argument(
        "--db-name",
        default=os.environ.get("POSTGRES_DB", DEFAULT_DB_NAME),
        help="Local Docker DB name (default: $POSTGRES_DB or 'jobsearch')",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt (required for unattended runs / Make targets)",
    )
    args = parser.parse_args()

    _load_dotenv()

    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "restore.sql.gz"

        if args.from_r2:
            client = _r2_client()
            bucket = os.environ["R2_BUCKET_NAME"]
            key = _pick_latest_pg_dump(client, bucket)
            print(f"\n  Source: r2://{bucket}/{key}")
            print(f"  Target: docker compose db ({args.db_user}@{args.db_name})")
        else:
            if not args.from_file or not args.from_file.exists():
                sys.exit(f"File not found: {args.from_file}")
            archive = args.from_file
            print(f"\n  Source: {archive} ({archive.stat().st_size / 1024:.1f} KB)")
            print(f"  Target: docker compose db ({args.db_user}@{args.db_name})")

        if not args.yes:
            answer = input("\nThis will OVERWRITE the local DB. Continue? [y/N] ").strip().lower()
            if answer != "y":
                print("Cancelled.")
                return 1

        if args.from_r2:
            _download_from_r2(client, bucket, key, archive)

        _restore_to_docker(archive, args.db_user, args.db_name)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
