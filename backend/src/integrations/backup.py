"""DB backup to Cloudflare R2 — JSON export of critical tables.

Exports job_analyses, interviews, cv_profiles, app_settings, todo_items,
contacts, cover_letters as gzipped JSON. Skips transient/regenerable
tables (audit_logs, batch_items, glassdoor_cache, notification_dismissals).

Each backup is stored under backups/{date}/{timestamp}.json.gz in R2.
Keeps last 7 backups by default (configurable).
"""

import gzip
import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from ..config import settings

logger = logging.getLogger(__name__)

# Retention: the daily cron creates one archive per run and we cap at 5
# rolling copies. The cleanup fires right after each upload, so the list
# naturally stays bounded — user feedback: "non voglio vedere l'elenco
# crescere all'infinito". 5 copies = ~5 days of point-in-time recovery
# which is enough for a single-user app; older backups rarely get
# restored and cost R2 storage + listing bandwidth for no real benefit.
MAX_BACKUPS = 5
BACKUP_PREFIX = "backups/"


def _serialize_row(row: Any) -> dict[str, Any]:
    """Convert a SQLAlchemy row to a JSON-safe dict."""
    d: dict[str, Any] = {}
    for col in row.__table__.columns:
        val = getattr(row, col.name)
        if val is None:
            d[col.name] = None
        elif hasattr(val, "isoformat"):
            d[col.name] = val.isoformat()
        elif hasattr(val, "hex"):
            d[col.name] = str(val)
        else:
            d[col.name] = val
    return d


def _export_table(db: Session, model: Any) -> list[dict[str, Any]]:
    """Export all rows from a table as a list of dicts."""
    return [_serialize_row(row) for row in db.query(model).all()]


def create_backup(db: Session) -> dict[str, Any]:
    """Export critical tables to gzipped JSON and upload to R2.

    Returns dict with backup metadata (key, size, table counts).
    """
    from ..agenda.models import TodoItem
    from ..analysis.models import AppSettings, JobAnalysis
    from ..contacts.models import Contact
    from ..cover_letter.models import CoverLetter
    from ..cv.models import CVProfile
    from ..interview.models import Interview

    tables = {
        "job_analyses": JobAnalysis,
        "interviews": Interview,
        "cv_profiles": CVProfile,
        "app_settings": AppSettings,
        "todo_items": TodoItem,
        "contacts": Contact,
        "cover_letters": CoverLetter,
    }

    now = datetime.now(UTC)
    export: dict[str, Any] = {
        "exported_at": now.isoformat(),
        "version": "2.0.0",
        "tables": {},
    }

    counts: dict[str, int] = {}
    for name, model in tables.items():
        rows = _export_table(db, model)
        export["tables"][name] = rows
        counts[name] = len(rows)

    # Compress
    json_bytes = json.dumps(export, ensure_ascii=False, default=str).encode("utf-8")
    compressed = gzip.compress(json_bytes, compresslevel=6)

    # Upload to R2
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H%M%S")
    r2_key = f"{BACKUP_PREFIX}{date_str}/{time_str}.json.gz"

    from .r2 import _get_r2_client

    client = _get_r2_client()
    client.put_object(
        Bucket=settings.r2_bucket_name,
        Key=r2_key,
        Body=compressed,
        ContentType="application/gzip",
    )

    size_kb = round(len(compressed) / 1024, 1)
    logger.info("Backup uploaded to R2: %s (%s KB)", r2_key, size_kb)

    # Cleanup old backups (keep MAX_BACKUPS)
    _cleanup_old_backups(client)

    return {
        "key": r2_key,
        "size_kb": size_kb,
        "original_size_kb": round(len(json_bytes) / 1024, 1),
        "counts": counts,
        "exported_at": now.isoformat(),
    }


def list_backups() -> list[dict[str, Any]]:
    """List existing backups in R2."""
    try:
        from .r2 import _get_r2_client

        client = _get_r2_client()
        response = client.list_objects_v2(
            Bucket=settings.r2_bucket_name,
            Prefix=BACKUP_PREFIX,
        )
        contents = response.get("Contents", [])
        return [
            {
                "key": obj["Key"],
                "size_kb": round(obj["Size"] / 1024, 1),
                "last_modified": obj["LastModified"].isoformat(),
            }
            for obj in sorted(contents, key=lambda x: x["LastModified"], reverse=True)
            if obj["Key"].endswith(".json.gz")
        ]
    except Exception:
        logger.exception("Failed to list backups from R2")
        return []


def _cleanup_old_backups(client: Any) -> int:
    """Remove old backups beyond MAX_BACKUPS limit. Returns count deleted."""
    try:
        response = client.list_objects_v2(
            Bucket=settings.r2_bucket_name,
            Prefix=BACKUP_PREFIX,
        )
        contents = response.get("Contents", [])
        gz_files = sorted(
            [obj for obj in contents if obj["Key"].endswith(".json.gz")],
            key=lambda x: x["LastModified"],
            reverse=True,
        )
        if len(gz_files) <= MAX_BACKUPS:
            return 0

        to_delete = gz_files[MAX_BACKUPS:]
        objects = [{"Key": obj["Key"]} for obj in to_delete]
        client.delete_objects(
            Bucket=settings.r2_bucket_name,
            Delete={"Objects": objects},
        )
        logger.info("Cleaned up %d old backups", len(objects))
        return len(objects)
    except Exception:
        logger.exception("Failed to cleanup old backups")
        return 0
