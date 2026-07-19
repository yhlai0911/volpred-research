#!/usr/bin/env python3
"""Open / inspect / close the dispatch burst window.

The window itself is `src/volpred/ops/dispatch_burst.py` — read its docstring
for why continuation is completion-driven and why expiry is the revert. This is
just the handle.

Usage::

    uv run python scripts/dispatch_burst_cli.py open \
        --until 2026-07-19T16:00:00+08:00 --reason "boss Telegram msg 1012-1014"
    uv run python scripts/dispatch_burst_cli.py status
    uv run python scripts/dispatch_burst_cli.py close      # early stop; expiry needs no close
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from volpred.ops import dispatch_burst  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("open")
    p.add_argument("--until", required=True, help="ISO datetime the burst ends (with offset)")
    p.add_argument("--reason", required=True)
    sub.add_parser("status")
    sub.add_parser("close")

    args = ap.parse_args()
    if args.cmd == "open":
        payload = dispatch_burst.open_window(
            until=args.until, reason=args.reason,
            opened_by=os.environ.get("VOLPRED_TASK_CLAIM_OWNER") or "cli",
        )
        out = {"ok": True, "opened": payload, "status": dispatch_burst.status()}
    elif args.cmd == "close":
        out = {"ok": True, "removed": dispatch_burst.close_window()}
    else:
        out = {"ok": True, "status": dispatch_burst.status()}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
