#!/usr/bin/env python3
"""Append one canonical Issue #46 retirement observation from live sources."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.audit_formal_owners import run_audit as run_formal_owner_audit
from volpred.ops.legacy_retirement import (
    append_current_retirement_observation,
    load_verified_retirement_observations,
)


def record() -> dict[str, object]:
    owner_report = run_formal_owner_audit(
        inventory_path=ROOT / "config" / "formal_capability_inventory.json",
        schedule_path=ROOT / "config" / "runtime_schedules.json",
    )
    observed_at = datetime.now(UTC)
    hour_start = observed_at.replace(minute=0, second=0, microsecond=0)
    path = append_current_retirement_observation(
        root=ROOT,
        owner_report=owner_report,
        observed_at=observed_at,
        batch_not_before=hour_start,
    )
    verified = load_verified_retirement_observations(ROOT)
    receipt = verified[-1]
    if receipt.get("receipt_id") != path.name:
        raise RuntimeError("legacy retirement observation append read-back drifted")
    return receipt


def main() -> int:
    try:
        receipt = record()
    except Exception as error:  # noqa: BLE001 - typed fail-loud CLI result.
        print(
            json.dumps(
                {
                    "schema_version": ("legacy-retirement-observation-error.v1"),
                    "ok": False,
                    "status": "observation_not_recorded",
                    "error": f"{type(error).__name__}: {error}",
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            {
                "schema_version": "legacy-retirement-observation-record.v1",
                "ok": True,
                "status": "observation_recorded",
                "receipt": receipt,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
