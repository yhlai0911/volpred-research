"""Backfill grandfathered activation receipts for currently-active strategies.

The five-check activation gate (docs/strategy-registry.md) was defined on
2026-03-29 (commit 2986a578f) — one day AFTER the last strategy was ever listed
(2026-03-28). Every currently-active strategy therefore predates the gate and
never went through it. Without a backfill, the very first time any active row's
Supabase record is deleted and re-created (the new-row activation path), the gate
would block a strategy that has been live for months.

This script reads the active strategies from `daily_update.STRATEGY_REGISTRY`
(the single source of truth for `is_active`) and writes one receipt each, marking
every gate `"grandfathered"` (NOT `true` — we do not falsely claim the checks
ran) with an explicit note that the gate postdates the listing.

By default this is a DRY RUN: it validates and prints the receipts it *would*
write and writes nothing. Pass `--apply` to actually write. (The task that
authored this script runs only `--dry-run`; a human/main-thread applies.)
"""

from __future__ import annotations

import argparse
import importlib
import json
from datetime import datetime, timezone

from volpred.ops.strategy_gate import (
    GATE_KEYS,
    receipt_path,
    receipts_dir,
    validate_receipt,
)

GRANDFATHER_APPROVER = "grandfathered-2026-03-29"
GATE_BIRTH_COMMIT = "2986a578f"
GATE_BIRTH_DATE = "2026-03-29"
LAST_LISTING_DATE = "2026-03-28"


def _active_strategies() -> dict[str, str]:
    """Return {strategy_key: display_name} for is_active=True registry rows."""
    registry = importlib.import_module("scripts.daily_update").STRATEGY_REGISTRY
    return {
        key: meta[0]
        for key, meta in registry.items()
        if meta[1] is True
    }


def _build_receipt(strategy_key: str, strategy_name: str) -> dict:
    return {
        "strategy_key": strategy_key,
        "strategy_name": strategy_name,
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "approved_by": GRANDFATHER_APPROVER,
        "gates": {key: "grandfathered" for key in GATE_KEYS},
        "evidence": {
            "grandfathered": True,
            "gate_birth_commit": GATE_BIRTH_COMMIT,
            "gate_birth_date": GATE_BIRTH_DATE,
            "last_listing_date": LAST_LISTING_DATE,
        },
        "note": (
            f"Grandfathered: the five-check activation gate was introduced "
            f"{GATE_BIRTH_DATE} (commit {GATE_BIRTH_COMMIT}), one day after the "
            f"last strategy was ever listed ({LAST_LISTING_DATE}). This strategy "
            f"has been live continuously and predates the gate, so no run of the "
            f"checks exists to record. Gates are marked 'grandfathered', not "
            f"'true'."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--apply", action="store_true", help="Write receipts to disk")
    group.add_argument(
        "--dry-run",
        action="store_true",
        help="Print receipts without writing (default)",
    )
    args = parser.parse_args()
    apply = args.apply  # dry-run is the default whenever --apply is absent

    active = _active_strategies()
    print(f"Active strategies in STRATEGY_REGISTRY: {len(active)}")
    print(f"Receipt directory: {receipts_dir()}")
    print(f"Mode: {'APPLY (writing)' if apply else 'DRY RUN (no writes)'}\n")

    wrote = 0
    for key, name in sorted(active.items()):
        receipt = _build_receipt(key, name)
        ok, reasons = validate_receipt(receipt)
        if not ok:
            # A malformed backfill receipt is a bug in this script, not a data
            # problem — fail loudly rather than write an invalid receipt.
            raise SystemExit(
                f"Refusing to emit invalid receipt for {key}: {'; '.join(reasons)}"
            )
        path = receipt_path(key)
        status = "exists" if path.exists() else "new"
        print(f"[{status:6}] {key}  ->  {path.name}")
        if apply:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            wrote += 1
        else:
            print(json.dumps(receipt, ensure_ascii=False, indent=2))

    if apply:
        print(f"\nWrote {wrote} receipt(s).")
    else:
        print(f"\nDRY RUN: would write {len(active)} receipt(s). Re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
