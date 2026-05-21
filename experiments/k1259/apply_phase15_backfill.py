#!/usr/bin/env python3
"""K1259 Phase 1.5 asset backfill applier.

Pins the 2026-04-20 main-thread asset-tag backfill so the full
two-step pipeline is reproducible:

    Phase 1:    build_dm_ledger.py        -> dm_ledger.json (Phase 1)
    Phase 1.5:  apply_phase15_backfill.py -> dm_ledger.json (Phase 1.5)

The original 2026-04-20 backfill was a one-off main-thread sweep:
read each K folder's README.md + *_results.json, infer ticker(s),
overwrite the empty asset field. We did not commit a generator
script that day; this applier is the post-hoc reconstruction
required by Codex review MAJOR-1 (2026-04-28).

Why a pinned map instead of re-deriving?
    The original backfill made judgment calls per-K (which README
    line is the "primary" ticker, how to merge JSON-listed assets
    with README narrative tickers, how to handle ambiguous K folder
    that mentions multiple assets in passing). Re-deriving without
    that human context risks drift. Pinning the 105-K asset map in
    `phase15_asset_map.json` and replaying it deterministically is
    the honest reproducible path. Future K additions should extend
    the map explicitly, not re-derive the existing entries.

Usage:
    # Step 1: regenerate fresh Phase 1 ledger
    python build_dm_ledger.py

    # Step 2: apply Phase 1.5 backfill
    python apply_phase15_backfill.py \\
        --in dm_ledger.json --out dm_ledger.json

Idempotent: re-applying on already-backfilled ledger is a no-op
(rows with asset_source already set are skipped).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_MAP = ROOT / "phase15_asset_map.json"
DEFAULT_LEDGER = ROOT / "dm_ledger.json"


def load_asset_map(path: Path) -> dict[str, dict[str, str]]:
    with path.open() as fh:
        obj = json.load(fh)
    raw = obj.get("map", {})
    if not isinstance(raw, dict):
        raise ValueError(f"phase15_asset_map.json has no 'map' object")
    return raw


def apply_backfill(
    ledger: dict[str, Any],
    asset_map: dict[str, dict[str, str]],
) -> tuple[dict[str, Any], dict[str, int]]:
    """Apply asset-tag backfill in-place; return (new_ledger, stats)."""
    rows = ledger.get("rows", [])
    stats = {
        "rows_input": len(rows),
        "rows_already_tagged": 0,
        "rows_singleton_filled": 0,
        "rows_multi_filled": 0,
        "rows_left_empty": 0,
        "rows_no_kid_mapping": 0,
    }

    new_rows = []
    for r in rows:
        if r.get("asset_source") in {
            "phase1.5_backfill_singleton",
            "phase1.5_backfill_multi",
        }:
            stats["rows_already_tagged"] += 1
            new_rows.append(r)
            continue

        if r.get("asset"):
            new_rows.append(r)
            continue

        k_id = r.get("k_id")
        if not k_id or k_id not in asset_map:
            stats["rows_left_empty"] += 1
            if k_id:
                stats["rows_no_kid_mapping"] += 1
            new_rows.append(r)
            continue

        entry = asset_map[k_id]
        new_row = dict(r)
        new_row["asset"] = entry["asset"]
        new_row["asset_source"] = entry["source"]
        if entry["source"] == "phase1.5_backfill_singleton":
            stats["rows_singleton_filled"] += 1
        else:
            stats["rows_multi_filled"] += 1
        new_rows.append(new_row)

    new_ledger = dict(ledger)
    new_ledger["rows"] = new_rows
    new_ledger["phase"] = "1.5_asset_backfill"
    new_ledger["phase15_applied_at"] = "2026-04-20T00:00:00+00:00"
    new_ledger["phase15_n_kids_in_map"] = len(asset_map)

    return new_ledger, stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--in", dest="in_path", default=str(DEFAULT_LEDGER))
    ap.add_argument("--out", dest="out_path", default=str(DEFAULT_LEDGER))
    ap.add_argument("--map", dest="map_path", default=str(DEFAULT_MAP))
    args = ap.parse_args()

    asset_map = load_asset_map(Path(args.map_path))
    print(f"[load] asset_map: {len(asset_map)} K-id entries")

    with Path(args.in_path).open() as fh:
        ledger = json.load(fh)
    print(f"[load] ledger: {len(ledger.get('rows', []))} rows, "
          f"phase={ledger.get('phase', 'unknown')}")

    new_ledger, stats = apply_backfill(ledger, asset_map)

    with Path(args.out_path).open("w") as fh:
        json.dump(new_ledger, fh, indent=2, ensure_ascii=False)

    print(f"[apply] stats:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"[done] wrote {args.out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
