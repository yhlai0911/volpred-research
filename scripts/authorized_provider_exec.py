#!/usr/bin/env python3
"""Authorize one provider contract, then replace this process with the CLI."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from volpred.ops.execution.registry import (  # noqa: E402
    ProviderRegistryError,
    authorize_provider_spawn,
    verify_spawn_receipt,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--executable", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    command = list(args.command)
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        print(
            "authorized-provider-exec: provider arguments are required after --",
            file=sys.stderr,
        )
        return 2
    try:
        receipt = authorize_provider_spawn(
            contract_id=args.contract,
            model_id=args.model,
            executable_path=args.executable,
            environment=os.environ,
        )
        verify_spawn_receipt(receipt)
    except ProviderRegistryError as exc:
        print(
            f"authorized-provider-exec: provider policy denied: {exc}",
            file=sys.stderr,
        )
        return 126
    child_env = {**os.environ, **receipt.environment()}
    provider_argv = [receipt.resolved_executable, *command]
    os.execve(receipt.resolved_executable, provider_argv, child_env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
