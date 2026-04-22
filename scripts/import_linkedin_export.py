#!/usr/bin/env python3
"""Import a LinkedIn 'Get a copy of your data' job-applications export.

Reads the three ``Job Applications*.csv`` files inside the archive produced
by LinkedIn's data export and upserts them into ``linkedin_applications``.

The table is created by Alembic migration 022; this script only writes data.
Re-running the script is safe: the unique constraint on
``(job_url, application_date)`` makes the insert idempotent.

Usage
-----

    # Archive already extracted (default layout from LinkedIn unzip):
    python scripts/import_linkedin_export.py /path/to/Basic_LinkedInDataExport_MM-DD-YYYY

    # Or point directly at the Jobs/ sub-folder:
    python scripts/import_linkedin_export.py --jobs-dir /path/to/.../Jobs

    # Dry run (parse but don't write):
    python scripts/import_linkedin_export.py --dry-run /path/to/archive

The script picks up ``DATABASE_URL`` from the environment. For local runs
point it at the dev/prod DSN exactly as the FastAPI app does.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Allow importing from backend/src when run from repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.linkedin_import.models import LinkedinApplication  # noqa: E402


def _parse_date(raw: str) -> datetime | None:
    """LinkedIn export format: '7/14/25, 9:02 AM'. Returns None on failure."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%m/%d/%y, %I:%M %p")
    except ValueError:
        return None


def _load_rows(jobs_dir: Path) -> list[dict[str, Any]]:
    """Read every Job Applications*.csv in ``jobs_dir`` and dedupe on (url, date)."""
    files = sorted(jobs_dir.glob("Job Applications*.csv"))
    if not files:
        raise SystemExit(f"No 'Job Applications*.csv' files found under {jobs_dir}")

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for f in files:
        with f.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                url = (row.get("Job Url") or "").strip()
                date_raw = (row.get("Application Date") or "").strip()
                key = (url, date_raw)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(
                    {
                        "application_date": _parse_date(date_raw),
                        "contact_email": (row.get("Contact Email") or "").strip() or None,
                        "contact_phone": (row.get("Contact Phone Number") or "").strip() or None,
                        "company_name": (row.get("Company Name") or "").strip() or None,
                        "job_title": (row.get("Job Title") or "").strip() or None,
                        "job_url": url or None,
                        "resume_name": (row.get("Resume Name") or "").strip() or None,
                        "question_and_answers": (row.get("Question And Answers") or "").strip() or None,
                    }
                )
    return rows


def _resolve_jobs_dir(archive_path: Path | None, jobs_dir: Path | None) -> Path:
    if jobs_dir is not None:
        return jobs_dir
    if archive_path is None:
        raise SystemExit("Provide the archive path or --jobs-dir")
    # Accept either the extracted folder or its Jobs/ subdir
    candidate = archive_path / "Jobs"
    if candidate.is_dir():
        return candidate
    if archive_path.is_dir() and any(archive_path.glob("Job Applications*.csv")):
        return archive_path
    raise SystemExit(f"Could not locate 'Jobs/' folder or 'Job Applications*.csv' files under {archive_path}")


def _get_dsn() -> str:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit(
            "DATABASE_URL not set. Export it to point at the target database (same value the FastAPI app uses)."
        )
    return dsn


def _insert_batched(
    dsn: str,
    rows: list[dict[str, Any]],
    batch_size: int = 200,
    dry_run: bool = False,
) -> int:
    if dry_run:
        return 0
    engine = create_engine(dsn, future=True)
    session_factory = sessionmaker(bind=engine, future=True)
    inserted = 0
    with session_factory() as session:
        for start in range(0, len(rows), batch_size):
            chunk = rows[start : start + batch_size]
            stmt = pg_insert(LinkedinApplication).values(chunk)
            stmt = stmt.on_conflict_do_nothing(constraint="uq_linkedin_apps_url_date")
            result = session.execute(stmt)
            inserted += result.rowcount or 0
            session.commit()
    return inserted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "archive",
        nargs="?",
        type=Path,
        help="Path to the extracted LinkedIn data archive (the folder containing Jobs/).",
    )
    parser.add_argument(
        "--jobs-dir",
        type=Path,
        help="Override: point directly at the Jobs/ subdirectory.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse the CSVs and print stats without touching the database.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Insert batch size (default 200).",
    )
    args = parser.parse_args()

    jobs_dir = _resolve_jobs_dir(args.archive, args.jobs_dir)
    rows = _load_rows(jobs_dir)
    print(f"Parsed {len(rows)} unique rows from {jobs_dir}")
    with_date = sum(1 for r in rows if r["application_date"])
    print(f"  - with application_date: {with_date}")
    print(f"  - missing application_date: {len(rows) - with_date}")

    if args.dry_run:
        print("Dry-run mode: nothing written.")
        return

    dsn = _get_dsn()
    inserted = _insert_batched(dsn, rows, batch_size=args.batch_size)
    print(f"Inserted {inserted} new rows (duplicates skipped via ON CONFLICT).")


if __name__ == "__main__":
    main()
