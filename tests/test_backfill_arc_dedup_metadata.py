from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import backfill_arc_dedup_metadata as backfill  # noqa: E402


def test_write_existing_single_files_syncs_patched_feed(tmp_path, monkeypatch):
    reports_dir = tmp_path / "storage" / "reports"
    reports_dir.mkdir(parents=True)
    single_path = reports_dir / "mile_test.json"
    single_path.write_text(
        json.dumps({"id": "mile_test", "details": {"old": True}}, indent=2),
        encoding="utf-8",
    )
    monkeypatch.setattr(backfill, "REPORTS_DIR", reports_dir)

    feed = [
        {
            "id": "mile_test",
            "title": "Updated",
            "details": {
                "arc_signature": {
                    "schema_version": "arc_dedup_v2",
                    "mechanisms": ["cross_asset_spillover"],
                }
            },
        },
        {"id": "mile_missing_single", "details": {"arc_signature": {}}},
    ]

    written = backfill._write_existing_single_files(
        feed,
        {"mile_test", "mile_missing_single"},
    )

    assert written == 1
    saved = json.loads(single_path.read_text(encoding="utf-8"))
    assert saved == feed[0]
