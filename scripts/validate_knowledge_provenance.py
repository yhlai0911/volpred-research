#!/usr/bin/env python3
"""CI invariant: knowledge.json provenance violation count must not exceed
the K1259 audit baseline (284 hard violations as of 2026-05-17).

Usage:
    uv run python scripts/validate_knowledge_provenance.py [--path PATH] [--baseline N]

Exit codes:
    0 = OK (count <= baseline; new entries are gated by writer validator)
    1 = REGRESSION (count > baseline; new violations have been introduced
        via jq/Edit hand-writes that bypass the Python writer)
    2 = file missing / unreadable

Background:
- v1 audit: 208 hard violations (V1=200 + V2=7 + V3=1)
- v2 audit: +76 numeric-near-keyword VIOLATION entries (47 WEAK separate)
- Hard baseline = 284 — see docs/knowledge_k1259_audit_v2_2026_05_17.md
- B1 data fix (commit 92e7cb52) partially applied; B2-B8 deferred
- Process-side gate at src/volpred/memory/system.py:_append_to_index
  prevents NEW Python writes from violating. This script catches hand-edits.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from volpred.memory.provenance import (  # noqa: E402
    KNOWN_VIOLATION_BASELINE,
    count_violations,
)

DEFAULT_PATH = ROOT / "storage" / "memory" / "knowledge.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--path", default=str(DEFAULT_PATH))
    ap.add_argument(
        "--baseline",
        type=int,
        default=KNOWN_VIOLATION_BASELINE,
        help=f"Max tolerated violation count (default: {KNOWN_VIOLATION_BASELINE})",
    )
    ap.add_argument(
        "--verbose",
        action="store_true",
        help="Print sample violation item_ids",
    )
    args = ap.parse_args()

    path = Path(args.path)
    if not path.exists():
        print(f"[validate-provenance] FAIL: {path} not found", file=sys.stderr)
        return 2

    try:
        with open(path, encoding="utf-8") as f:
            entries = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[validate-provenance] FAIL: cannot parse {path}: {exc}", file=sys.stderr)
        return 2

    if not isinstance(entries, list):
        print(f"[validate-provenance] FAIL: {path} is not a list", file=sys.stderr)
        return 2

    if not entries:
        # A ratchet compares violations against a baseline, and zero entries
        # yield zero violations -- so a truncated or wrongly-pathed
        # knowledge.json reads as PERFECTLY CLEAN and returns 0. An empty
        # knowledge base is a catastrophe, not a clean bill of health
        # (docs/error_log.md 2026-08-04: a gate that inspects an empty set must
        # fail, because every check it performs is vacuously true).
        print(
            f"[validate-provenance] FAIL: {path} holds no entries. An empty "
            "knowledge base cannot be validated -- zero violations here means "
            "the file is missing content, not that provenance is clean.",
            file=sys.stderr,
        )
        return 2

    n = count_violations(entries)
    total = len(entries)

    msg = (
        f"[validate-provenance] knowledge.json: {n}/{total} hard provenance "
        f"violations (baseline={args.baseline})"
    )

    if n > args.baseline:
        print(msg + "  -> REGRESSION", file=sys.stderr)
        print(
            "[validate-provenance] New violations introduced since 2026-05-17 "
            "audit. Likely hand-edits via jq/Edit bypassed the Python writer "
            "gate at src/volpred/memory/system.py:_append_to_index.",
            file=sys.stderr,
        )
        if args.verbose:
            from volpred.memory.provenance import validate_provenance

            bad = []
            for e in entries:
                try:
                    validate_provenance(e)
                except ValueError:
                    bad.append(e.get("item_id") or e.get("id") or "?")
            print(
                f"[validate-provenance] sample violating item_ids: {bad[:10]}",
                file=sys.stderr,
            )
        return 1

    print(msg + "  -> OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
