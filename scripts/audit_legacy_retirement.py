#!/usr/bin/env python3
"""Audit whether the legacy hourly-dispatch executor is physically retired."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.audit_formal_owners import (
    run_audit as run_formal_owner_audit,
)
from volpred.ops.legacy_retirement import (
    LegacyRetirementInputError,
    assess_hourly_dispatch_retirement,
    assess_sustained_clean_receipts,
    load_verified_retirement_observations,
)

LIVE_WRAPPER = Path.home() / ".volpred" / "bin" / "cron_hourly_dispatch.sh"
LEGACY_LABEL = "com.volpred.hourly-dispatch"


def _load_observations(root: Path = ROOT) -> list[Mapping[str, Any]]:
    return load_verified_retirement_observations(root)


def _probe_host(
    *,
    observed_at: datetime,
    live_wrapper: Path = LIVE_WRAPPER,
) -> dict[str, object]:
    try:
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as error:
        raise LegacyRetirementInputError(
            f"launchctl owner probe failed: {type(error).__name__}: {error}"
        ) from error
    labels = {
        fields[-1] for line in result.stdout.splitlines() if (fields := line.split())
    }
    return {
        "schema_version": "legacy-retirement-host-evidence.v1",
        "label": LEGACY_LABEL,
        "label_loaded": LEGACY_LABEL in labels,
        "live_wrapper": str(live_wrapper),
        "live_wrapper_exists": os.path.lexists(live_wrapper),
        "observed_at": observed_at.astimezone(UTC).isoformat(),
    }


def run_audit(
    *,
    root: Path = ROOT,
    assessed_at: datetime | None = None,
    owner_auditor: Callable[..., Mapping[str, object]] = run_formal_owner_audit,
    host_probe: Callable[..., Mapping[str, object]] = _probe_host,
) -> dict[str, object]:
    now = (assessed_at or datetime.now(UTC)).astimezone(UTC)
    owner_report = owner_auditor(
        inventory_path=root / "config" / "formal_capability_inventory.json",
        schedule_path=root / "config" / "runtime_schedules.json",
    )
    observations = _load_observations(root)
    sustained = assess_sustained_clean_receipts(
        observations,
        assessed_at=now,
    )
    host = host_probe(observed_at=now)
    retirement = assess_hourly_dispatch_retirement(
        root=root,
        owner_report=owner_report,
        sustained_clean_report=sustained.as_dict(),
        host_evidence=host,
        assessed_at=now,
    )
    return {
        **retirement.as_dict(),
        "formal_owner_census": owner_report,
        "sustained_clean": sustained.as_dict(),
        "host_evidence": dict(host),
        "observation_directory": str(
            root / "storage" / "ops" / "legacy_retirement_observations"
        ),
    }


def main() -> int:
    try:
        report = run_audit()
    except Exception as error:  # noqa: BLE001 - CLI emits a typed failure.
        print(
            json.dumps(
                {
                    "schema_version": "legacy-execution-retirement-error.v1",
                    "ready": False,
                    "status": "audit_failed",
                    "error": f"{type(error).__name__}: {error}",
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
