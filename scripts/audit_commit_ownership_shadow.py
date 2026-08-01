#!/usr/bin/env python3
"""Audit the retired manifest Stage-2 shadow without authorizing Stage 3."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from croniter import croniter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from scripts.dispatch_supervisor.phase_z import is_machine_state_path
from volpred.ops import fire_manifest


def _load_shadow(path: Path) -> tuple[list[dict[str, Any]], bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise fire_manifest.FireManifestError(
            f"shadow evidence unavailable: {path}: {exc}"
        ) from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise fire_manifest.FireManifestError(
            "shadow evidence is not valid UTF-8"
        ) from exc

    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise fire_manifest.FireManifestError(
                f"shadow evidence line {line_number} is invalid JSON"
            ) from exc
        if not isinstance(record, dict):
            raise fire_manifest.FireManifestError(
                f"shadow evidence line {line_number} is not an object"
            )
        records.append(record)
    if not records:
        raise fire_manifest.FireManifestError("shadow evidence is empty")
    return records, raw


def _default_path_classifier(path: str) -> str:
    return "machine_state" if is_machine_state_path(path) else "non_machine"


def _load_expected_fires(root: Path) -> list[dict[str, Any]]:
    """Strictly load the git-common-dir manifest population for reconciliation."""
    manifests: list[dict[str, Any]] = []
    for path in sorted(fire_manifest.manifest_dir(root).glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise fire_manifest.FireManifestError(
                f"expected fire manifest unreadable: {path}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise fire_manifest.FireManifestError(
                f"expected fire manifest is not an object: {path}"
            )
        manifests.append(payload)
    return manifests


def _load_schedule(root: Path) -> tuple[str, Path]:
    path = root / "config" / "runtime_schedules.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise fire_manifest.FireManifestError(
            f"canonical dispatch schedule unavailable: {path}: {exc}"
        ) from exc
    for item in payload.get("cron_jobs", []):
        if not isinstance(item, dict) or item.get("id") != "volpred-hourly-dispatch":
            continue
        expression = item.get("schedule")
        if isinstance(expression, str) and expression.strip():
            expression = expression.strip()
            if not croniter.is_valid(expression):
                raise fire_manifest.FireManifestError(
                    f"canonical dispatch schedule is invalid: {expression!r}"
                )
            return expression, path
    raise fire_manifest.FireManifestError(
        "canonical volpred-hourly-dispatch schedule is missing"
    )


def _schedule_slots(
    expression: str,
    *,
    start: datetime,
    end: datetime,
) -> list[datetime]:
    cursor = croniter(expression, start - timedelta(seconds=1))
    slots: list[datetime] = []
    while True:
        slot = cursor.get_next(datetime)
        if slot > end:
            break
        slots.append(slot.astimezone(UTC))
    return slots


def run_audit(
    *,
    root: Path = ROOT,
    assessed_at: datetime | None = None,
    classify_path: Callable[[str], str] = _default_path_classifier,
) -> dict[str, Any]:
    root = Path(root).resolve()
    assessed_at = (assessed_at or datetime.now(UTC)).astimezone(UTC)
    shadow = fire_manifest.shadow_log_path(root)
    records, raw = _load_shadow(shadow)
    expected_fires = _load_expected_fires(root)
    schedule_expression, schedule_path = _load_schedule(root)
    schedule_slots = _schedule_slots(
        schedule_expression,
        start=assessed_at - timedelta(days=7),
        end=assessed_at,
    )
    report = fire_manifest.assess_shadow_records(
        records,
        assessed_at=assessed_at,
        expected_fires=expected_fires,
        expected_schedule=schedule_slots,
        classify_path=classify_path,
    )
    return {
        **report,
        "evidence": {
            "path": str(shadow),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "records": len(records),
            "expected_manifest_records": len(expected_fires),
            "schedule_path": str(schedule_path),
            "schedule_expression": schedule_expression,
        },
        "interpretation": {
            "declaration_gap": (
                "Legacy PostToolUse declarations omit Bash/Codex and are no longer "
                "the canonical producer-ownership source."
            ),
            "machine_state_gap": (
                "Machine-state occurrences exit through Issue #41 single-writer "
                "ownership after Issue #9 cutover."
            ),
            "non_machine_gap": (
                "Canonical-root non-machine residue is foreign; Issue #43 worker "
                "output lands only through isolated workspace settlement."
            ),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(ROOT))
    args = parser.parse_args(argv)
    try:
        report = run_audit(root=Path(args.repo_root))
    except Exception as exc:  # noqa: BLE001 - emit one typed fail-closed result.
        print(json.dumps({
            "schema_version": "commit-ownership-shadow-assessment-error.v1",
            "legacy_stage2_metrics_pass": False,
            "manifest_cutover_eligible": False,
            "status": "audit_failed",
            "error": f"{type(exc).__name__}: {exc}",
        }, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    # This is a cutover audit, not a data-export command. A green historical
    # metric window still cannot authorize the superseded contract, so exit 0
    # would be an unsafe false-ready signal to any shell caller.
    return 0 if report["manifest_cutover_eligible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
