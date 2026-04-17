#!/usr/bin/env python3
"""Export full analyses dataset from production to local JSON.

Hits /api/v1/admin/export/analyses with API_KEY auth and saves to
data/analyses_export_YYYYMMDD.json for offline pandas analysis.

Usage:
    python scripts/export_db.py
    python scripts/export_db.py --base-url https://www.jobsearches.cc
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

DEFAULT_BASE = "https://www.jobsearches.cc"
ENDPOINT = "/api/v1/admin/export/analyses"


def load_api_key() -> str:
    key = os.environ.get("API_KEY", "").strip()
    if key:
        return key
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("API_KEY="):
                return line.split("=", 1)[1].strip()
    sys.exit("API_KEY not found in env or .env")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--output-dir", default="data")
    args = parser.parse_args()

    api_key = load_api_key()
    url = args.base_url.rstrip("/") + ENDPOINT

    print(f"Fetching {url} ...")
    resp = httpx.get(url, headers={"X-API-Key": api_key, "Accept": "application/json"}, timeout=60.0)
    resp.raise_for_status()
    payload = resp.json()

    total = payload.get("total", 0)
    print(f"Received {total} analyses")

    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir)
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"analyses_export_{stamp}.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    (out_dir / "analyses_latest.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    size_kb = out_path.stat().st_size / 1024
    print(f"Saved {total} analyses to {out_path} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
