#!/usr/bin/env python3
"""K1174 — GDELT BigQuery fetch (primary path, disabled).

Design (when GCP credentials available):
  SELECT DocumentIdentifier, V2Persons, V2Organizations, DATE
  FROM `gdelt-bq.gdeltv2.gkg`
  WHERE DATE BETWEEN earnings_T-2 AND earnings_T+2
    AND (V2Persons LIKE '%COMPANY_NAME%' OR V2Organizations LIKE '%COMPANY_NAME%')

Status on 2026-04-13 execution host:
  - No `gcloud` / `bq` CLI installed.
  - No `google-cloud-bigquery` Python package installed.
  - No application default credentials (`gcloud auth application-default login`).
  - Installing unreviewed GCP packages + authenticating interactively is out of
    scope for an autonomous worktree agent. This script is therefore retained as
    a recipe for future rerun on a host with GCP credentials.

Fallback used by K1174: raw GDELT GKG CSV.zip files via HTTP, 1 file per
unique earnings-window day (12:00 UTC slice). See `k1174_fetch_gdelt_files.py`.

Reference: https://blog.gdeltproject.org/gdelt-2-0-our-global-world-in-realtime/
Random seed: 42.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
DATA.mkdir(parents=True, exist_ok=True)

STATUS = {
    "attempted": False,
    "reason": (
        "GCP tooling (gcloud/bq CLI and google-cloud-bigquery Python library)"
        " not available on execution host; no authentication flow feasible"
        " inside an autonomous worktree agent."
    ),
    "recipe_for_future_rerun": {
        "dataset": "gdelt-bq.gdeltv2.gkg",
        "example_sql": (
            "SELECT DATE(PARSE_TIMESTAMP('%Y%m%d%H%M%S', CAST(DATE AS STRING))) d,"
            " COUNT(*) n"
            " FROM `gdelt-bq.gdeltv2.gkg`"
            " WHERE CAST(DATE AS STRING) BETWEEN '20240401000000' AND '20240421000000'"
            " AND (LOWER(V2Persons) LIKE '%tsmc%' OR LOWER(V2Organizations) LIKE '%tsmc%')"
            " GROUP BY d ORDER BY d"
        ),
        "max_bytes_billed": 1_000_000_000_000,  # 1 TB guardrail per query
        "notes": (
            "The gkg table is partitioned by DATE; restrict to a specific"
            " earnings window to avoid scanning multi-TB years. One query per"
            " stock × (list of events) is feasible in BigQuery; for K1174's"
            " ~250 events across 35 stocks this fits in one interactive session."
        ),
    },
    "fallback_script": "k1174_fetch_gdelt_files.py",
}

if __name__ == "__main__":
    out = DATA / "bigquery_status.json"
    out.write_text(json.dumps(STATUS, indent=2), encoding="utf-8")
    print(json.dumps(STATUS, indent=2))
    print(f"\nWrote {out}", file=sys.stderr)
    # Exit non-zero so an outer orchestrator knows to fall back.
    sys.exit(2)
