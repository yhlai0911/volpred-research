#!/usr/bin/env python3
"""Audit every registered lock/gate and optionally actuate its PDCA review."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from volpred.ops.control_gate_lifecycle import (  # noqa: E402
    DEFAULT_REGISTRY_PATH,
    audit_control_gates,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-dir", default="storage")
    parser.add_argument(
        "--registry",
        default=str(DEFAULT_REGISTRY_PATH),
    )
    parser.add_argument(
        "--materialize-reviews",
        action="store_true",
        help="Create due review tasks through canonical next_tasks ingress.",
    )
    parser.add_argument(
        "--write-state",
        action="store_true",
        help="Persist storage/ops/control_gate_lifecycle_latest.json.",
    )
    args = parser.parse_args()
    verdict = audit_control_gates(
        storage_dir=args.storage_dir,
        registry_path=args.registry,
        materialize_reviews=args.materialize_reviews,
        write_state=args.write_state,
    )
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 1 if verdict["summary"]["review_due_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
