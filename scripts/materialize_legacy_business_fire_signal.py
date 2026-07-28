#!/usr/bin/env python3
"""Materialize Operations Core's canonical legacy-business-fire signal."""

from __future__ import annotations

from pathlib import Path

from volpred.ops.legacy_retirement import retirement_signal_batch_lock
from volpred.ops.legacy_retirement_events import (
    materialize_legacy_business_fire_signal,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with retirement_signal_batch_lock(ROOT):
        print(materialize_legacy_business_fire_signal(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
