#!/usr/bin/env python3
"""Fail-closed tripwire for the retired legacy hourly dispatcher."""

from __future__ import annotations

import argparse
from pathlib import Path

from volpred.ops.legacy_retirement_events import append_legacy_business_fire

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--materialize-signal",
        action="store_true",
        help="Reserved for Operations Core; legacy entrypoints must not use it.",
    )
    args = parser.parse_args()
    if args.materialize_signal:
        parser.error("legacy entrypoint cannot self-certify its retirement signal")
    path = append_legacy_business_fire(ROOT)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
