"""Operational CLI for dispatch supervisor state.

Usage::

    uv run python -m scripts.dispatch_supervisor.cli status
    uv run python -m scripts.dispatch_supervisor.cli unblock-auth
    uv run python -m scripts.dispatch_supervisor.cli health-check
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import health, state


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="dispatch-supervisor-cli")
    parser.add_argument(
        "--state-path",
        default=str(state.STATE_PATH),
        help="Override dispatch_state.json path for tests or local smoke checks.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Print current supervisor state as JSON.")
    sub.add_parser("unblock-auth", help="Clear auth_blocked flag after manual auth recovery.")
    sub.add_parser("health-check", help="Run one synchronous health check pass.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    state_path = Path(args.state_path)

    if args.command == "status":
        print(json.dumps(state.read_state(state_path), indent=2, ensure_ascii=False))
        return 0

    if args.command == "unblock-auth":
        state.set_auth_blocked(False, path=state_path)
        print(json.dumps({
            "ok": True,
            "command": "unblock-auth",
            "auth_blocked": False,
            "state_path": str(state_path),
        }, ensure_ascii=False))
        return 0

    if args.command == "health-check":
        action = health.check_once(state_path=state_path)
        print(json.dumps({
            "ok": True,
            "command": "health-check",
            "action": action,
            "state_path": str(state_path),
        }, ensure_ascii=False))
        return 0

    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
