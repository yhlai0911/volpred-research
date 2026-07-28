#!/usr/bin/env python3
"""Refresh all Issue #46 retirement signals as one observer-visible batch."""

from __future__ import annotations

from pathlib import Path

from volpred.ops.legacy_retirement import retirement_signal_batch_lock
from volpred.ops.legacy_retirement_events import (
    materialize_duplicate_effect_signal,
    materialize_legacy_business_fire_signal,
    materialize_orphan_work_signal,
)
from volpred.ops.silent_loss_retirement import materialize_silent_loss_signal

ROOT = Path(__file__).resolve().parents[1]


def materialize(root: Path = ROOT) -> list[Path]:
    repo_root = Path(root)
    with retirement_signal_batch_lock(repo_root):
        return [
            materialize_legacy_business_fire_signal(repo_root),
            materialize_duplicate_effect_signal(repo_root),
            materialize_orphan_work_signal(repo_root),
            materialize_silent_loss_signal(repo_root),
        ]


def main() -> int:
    for path in materialize():
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
