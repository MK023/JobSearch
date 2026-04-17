#!/usr/bin/env python3
"""Run analytics on an exported analyses dump and save a markdown report.

Uses backend.src.analytics modules (same code that will power the future
POST /api/v1/admin/run-analytics endpoint).

Usage:
    python scripts/export_db.py             # first, export
    python scripts/analyze_db.py            # then, analyze latest
    python scripts/analyze_db.py --input data/analyses_export_20260417.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

# Allow importing from backend/src when run from repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from src.analytics import build_report  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/analyses_latest.json")
    parser.add_argument("--output-dir", default="data")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        sys.exit(f"Input not found: {input_path}. Run scripts/export_db.py first.")

    payload = json.loads(input_path.read_text())
    analyses = payload.get("analyses", [])
    print(f"Loaded {len(analyses)} analyses from {input_path}")

    report = build_report(analyses)

    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir)
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"analysis_report_{stamp}.md"
    out_path.write_text(report)

    latest = out_dir / "analysis_report_latest.md"
    latest.write_text(report)

    print(f"Report written: {out_path}")
    print(f"Latest: {latest}")


if __name__ == "__main__":
    main()
